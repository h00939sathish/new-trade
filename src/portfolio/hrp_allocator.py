import logging
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform
from typing import Any

logger = logging.getLogger("portfolio.hrp")

class HierarchicalRiskParity:
    """
    Hierarchical Risk Parity (HRP) Portfolio Allocator.
    - Uses hierarchical clustering to group correlated assets.
    - Allocates capital recursively based on inverse variance.
    - Avoids inversion of the covariance matrix.
    """
    def __init__(self):
        pass

    def _get_distance_matrix(self, corr: pd.DataFrame) -> pd.DataFrame:
        """Calculate distance matrix from correlation matrix."""
        # distance d(i,j) = sqrt(0.5 * (1 - corr(i,j)))
        return np.sqrt(np.clip(0.5 * (1 - corr), 0, 1))

    def _get_quasi_diag(self, link: np.ndarray) -> list[int]:
        """Sort clustered items by distance."""
        link = link.astype(int)
        sort_ix = pd.Series([link[-1, 0], link[-1, 1]])
        num_items = link[-1, 3]
        
        while sort_ix.max() >= num_items:
            sort_ix.index = range(0, sort_ix.shape[0] * 2, 2)  # make space
            df0 = sort_ix[sort_ix >= num_items]  # find clusters
            i = df0.index
            j = df0.values - num_items
            sort_ix[i] = link[j, 0]  # item 1
            df0 = pd.Series(link[j, 1], index=i + 1)
            sort_ix = pd.concat([sort_ix, df0])  # item 2
            sort_ix = sort_ix.sort_index()
            sort_ix.index = range(sort_ix.shape[0])
            
        return sort_ix.tolist()

    def _get_rec_bipart(self, cov: pd.DataFrame, sort_ix: list[int]) -> pd.Series:
        """Compute HRP allocations."""
        w = pd.Series(1, index=sort_ix)
        c_items = [sort_ix]  # initialize all items in one cluster
        
        while len(c_items) > 0:
            c_items = [i[j:k] for i in c_items for j, k in ((0, len(i) // 2), (len(i) // 2, len(i))) if len(i) > 1]
            
            for i in range(0, len(c_items), 2):
                c_items0 = c_items[i]  # cluster 1
                c_items1 = c_items[i + 1]  # cluster 2
                
                c_var0 = self._get_cluster_var(cov, c_items0)
                c_var1 = self._get_cluster_var(cov, c_items1)
                
                alpha = 1 - c_var0 / (c_var0 + c_var1)
                
                w[c_items0] *= alpha  # weight 1
                w[c_items1] *= 1 - alpha  # weight 2
                
        return w

    def _get_cluster_var(self, cov: pd.DataFrame, c_items: list[int]) -> float:
        """Calculate variance of a cluster."""
        cov_ = cov.iloc[c_items, c_items]  # matrix slice
        ivp = 1. / np.diag(cov_)
        ivp /= ivp.sum()
        w_ = ivp.reshape(-1, 1)
        c_var = np.dot(np.dot(w_.T, cov_), w_)[0, 0]
        return c_var

    def allocate(self, returns_dict: dict[str, list[float]]) -> dict[str, float]:
        """
        Allocate portfolio weights based on a dictionary of historical returns.
        Returns: {instrument: weight}
        """
        if not returns_dict or len(returns_dict) < 2:
            return {k: 1.0 for k in returns_dict.keys()}
            
        # Ensure all return lists have the same length
        min_len = min(len(v) for v in returns_dict.values())
        if min_len < 10:
            logger.warning("Not enough history for HRP, returning equal weights")
            return {k: 1.0 / len(returns_dict) for k in returns_dict.keys()}
            
        aligned_returns = {k: v[-min_len:] for k, v in returns_dict.items()}
        df = pd.DataFrame(aligned_returns)
        
        cov = df.cov()
        corr = df.corr()
        
        dist = self._get_distance_matrix(corr)
        
        # Linkage
        try:
            # We use condensed distance matrix
            link = linkage(squareform(dist), method='single')
            sort_ix = self._get_quasi_diag(link)
            sort_ix = sort_ix[::-1]  # reverse
            
            weights = self._get_rec_bipart(cov, sort_ix)
            weights.index = [df.columns[i] for i in weights.index]
            return weights.to_dict()
            
        except Exception as e:
            logger.error("HRP allocation failed: %s", e)
            return {k: 1.0 / len(returns_dict) for k in returns_dict.keys()}
