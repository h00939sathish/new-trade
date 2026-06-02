import logging
from typing import Any
import numpy as np

try:
    from sklearn.decomposition import PCA
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

from src.strategies.base import Strategy

logger = logging.getLogger("strategies.pca_statarb")

class PCAStatArbStrategy(Strategy):
    """
    PCA-Based Statistical Arbitrage.
    - Maintains a rolling window of returns for a basket of assets.
    - Extracts principal components to model the 'market' factor.
    - Computes residuals of the current asset relative to the PCA reconstruction.
    - Enters LONG if residual z-score < -2.0, SHORT if > +2.0.
    """
    def __init__(self, window: int = 60, n_components: int = 1, entry_z: float = 2.0, exit_z: float = 0.5):
        self.name = "pca_statarb"
        self.data_type = "candle"
        self.timeframe = "minute"
        self.window = window
        self.n_components = n_components
        self.entry_z = entry_z
        self.exit_z = exit_z
        
        # Internal cache to maintain the cross-asset matrix
        # Maps instrument -> list of recent prices
        self._price_cache: dict[str, list[float]] = {}
        
    async def evaluate(
        self,
        instrument: str,
        prices: list[float],
        volumes: list[float] | None = None,
        highs: list[float] | None = None,
        lows: list[float] | None = None,
        timestamps: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        
        if not SKLEARN_AVAILABLE:
            return None
            
        if len(prices) < self.window + 1:
            return None
            
        # Update cache for this instrument
        self._price_cache[instrument] = prices[-(self.window + 1):]
        
        # We need at least N instruments to do meaningful PCA
        valid_instruments = [inst for inst, p in self._price_cache.items() if len(p) == self.window + 1]
        
        if len(valid_instruments) < max(3, self.n_components + 1):
            return None
            
        # Build return matrix
        ret_matrix = []
        inst_list = []
        for inst in valid_instruments:
            p = self._price_cache[inst]
            ret = np.diff(p) / p[:-1]
            ret_matrix.append(ret)
            inst_list.append(inst)
            
        # Shape: (n_samples, n_features) where features = instruments
        # We want to fit PCA on the returns to find the common components
        X = np.column_stack(ret_matrix)
        
        # Standardize returns
        means = np.mean(X, axis=0)
        stds = np.std(X, axis=0)
        
        # Avoid division by zero
        stds[stds == 0] = 1e-8
        
        X_scaled = (X - means) / stds
        
        pca = PCA(n_components=self.n_components)
        try:
            pca.fit(X_scaled)
        except Exception as e:
            logger.debug(f"PCA fit failed: {e}")
            return None
            
        # Reconstruct the returns using PCA
        X_projected = pca.transform(X_scaled)
        X_reconstructed = pca.inverse_transform(X_projected)
        
        # Residuals = Actual - Reconstructed
        residuals = X_scaled - X_reconstructed
        
        # We focus on the target instrument's residuals
        try:
            target_idx = inst_list.index(instrument)
        except ValueError:
            return None
            
        target_residuals = residuals[:, target_idx]
        
        # Calculate z-score of the current residual relative to the window
        current_residual = target_residuals[-1]
        mean_res = np.mean(target_residuals)
        std_res = np.std(target_residuals)
        
        if std_res == 0:
            return None
            
        z_score = (current_residual - mean_res) / std_res
        
        direction = None
        if z_score < -self.entry_z:
            direction = "long"
        elif z_score > self.entry_z:
            direction = "short"
            
        if not direction:
            return None
            
        return {
            "direction": direction,
            "confidence": min(1.0, abs(z_score) / 4.0),
            "price": prices[-1],
            "features": {
                "pca_z_score": float(z_score),
                "pca_residual": float(current_residual),
                "pca_explained_variance": float(np.sum(pca.explained_variance_ratio_))
            },
        }
