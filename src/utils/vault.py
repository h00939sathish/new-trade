import os
import logging
import httpx
from typing import Any

logger = logging.getLogger("utils.vault")


def get_secret_from_vault(secret_path: str, secret_key: str) -> str | None:
    """Retrieve secret from HashiCorp Vault."""
    vault_addr = os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
    vault_token = os.environ.get("VAULT_TOKEN")
    if not vault_token:
        logger.warning("VAULT_TOKEN environment variable not set.")
        return None
    try:
        # KV V2 API: GET /v1/secret/data/{secret_path}
        headers = {"X-Vault-Token": vault_token}
        url = f"{vault_addr}/v1/secret/data/{secret_path}"
        with httpx.Client(timeout=5) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json().get("data", {}).get("data", {})
                return data.get(secret_key)
            
            # KV V1 API fallback: GET /v1/{secret_path}
            url_v1 = f"{vault_addr}/v1/{secret_path}"
            resp_v1 = client.get(url_v1, headers=headers)
            if resp_v1.status_code == 200:
                data = resp_v1.json().get("data", {})
                return data.get(secret_key)
            
            logger.warning("Vault returned status %d for path %s", resp.status_code, secret_path)
    except Exception as e:
        logger.error("Error fetching secret from Vault: %s", e)
    return None


def get_secret_from_aws(secret_id: str, secret_key: str) -> str | None:
    """Retrieve secret from AWS Secrets Manager. Requires the [vault] extra."""
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "AWS Secrets Manager support requires boto3. "
            "Install with: pip install -e \".[vault]\" (or include the [vault] extra)."
        ) from exc
    try:
        import json
        region_name = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        session = boto3.session.Session()
        client = session.client(
            service_name="secretsmanager",
            region_name=region_name
        )
        response = client.get_secret_value(SecretId=secret_id)
        if "SecretString" in response:
            secret = response["SecretString"]
            try:
                secret_dict = json.loads(secret)
                return secret_dict.get(secret_key)
            except json.JSONDecodeError:
                return secret
    except Exception as e:
        logger.error("Error fetching secret from AWS Secrets Manager: %s", e)
    return None


def load_secure_secret(env_var_name: str, vault_path: str = None, vault_key: str = None, aws_secret_id: str = None, aws_secret_key: str = None) -> str:
    """Load secret from configured Vault provider, falling back to environment variable."""
    provider = os.environ.get("TRA_VAULT_PROVIDER", "").lower()
    
    if not vault_path:
        vault_path = "trading-system"
    if not vault_key:
        vault_key = env_var_name.replace("TRA_", "").lower()
    if not aws_secret_id:
        aws_secret_id = "trading-system"
    if not aws_secret_key:
        aws_secret_key = env_var_name.replace("TRA_", "").lower()

    if provider == "vault":
        val = get_secret_from_vault(vault_path, vault_key)
        if val:
            logger.debug("Successfully loaded secret %s from HashiCorp Vault", env_var_name)
            return val
    elif provider == "aws":
        val = get_secret_from_aws(aws_secret_id, aws_secret_key)
        if val:
            logger.debug("Successfully loaded secret %s from AWS Secrets Manager", env_var_name)
            return val
            
    return os.environ.get(env_var_name, "")
