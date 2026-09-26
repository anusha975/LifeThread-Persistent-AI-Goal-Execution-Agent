import logging
import os
from typing import Any

from botocore.config import Config

from app.core.config import get_settings

logger = logging.getLogger("lifethread.aws.config")


class AWSConfigManager:
    """Manages secure AWS credential resolution, botocore policies, and client instantiation."""

    @staticmethod
    def get_masked_credentials() -> dict[str, Any]:
        """Return masked AWS configuration for audit logs and system status."""
        settings = get_settings()
        ak = settings.AWS_ACCESS_KEY_ID or os.environ.get("AWS_ACCESS_KEY_ID")
        role_arn = settings.AWS_ROLE_ARN or os.environ.get("AWS_ROLE_ARN")

        has_keys = bool(ak and len(ak) > 4)
        masked_ak = f"{ak[:4]}...{ak[-4:]}" if has_keys and ak and len(ak) >= 8 else ("Configured" if ak else "None")

        return {
            "region": settings.AWS_REGION,
            "has_credentials": bool(ak or role_arn),
            "access_key_masked": masked_ak,
            "role_arn": role_arn or "None",
            "default_model": settings.AWS_BEDROCK_DEFAULT_MODEL,
            "fast_model": settings.AWS_BEDROCK_FAST_MODEL,
            "timeout_seconds": settings.AWS_BEDROCK_TIMEOUT_SECONDS,
            "max_retries": settings.AWS_BEDROCK_MAX_RETRIES,
            "fallback_enabled": settings.AWS_BEDROCK_FALLBACK_ON_ERROR,
            "agent_id_configured": bool(settings.AWS_AGENTCORE_AGENT_ID),
            "knowledge_base_id_configured": bool(settings.AWS_STRANDS_KNOWLEDGE_BASE_ID),
        }

    @classmethod
    def get_botocore_config(
        cls,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> Config:
        """Create botocore Config with adaptive retry backoff and deterministic timeouts."""
        settings = get_settings()
        effective_timeout = timeout or settings.AWS_BEDROCK_TIMEOUT_SECONDS
        effective_retries = max_retries if max_retries is not None else settings.AWS_BEDROCK_MAX_RETRIES

        return Config(
            region_name=settings.AWS_REGION,
            connect_timeout=effective_timeout,
            read_timeout=effective_timeout,
            retries={
                "max_attempts": effective_retries,
                "mode": "adaptive",
            },
        )

    @classmethod
    def create_boto3_session(cls) -> Any:
        """Create a boto3 Session respecting configured keys or environment role assumption."""
        import boto3

        settings = get_settings()
        ak = settings.AWS_ACCESS_KEY_ID or os.environ.get("AWS_ACCESS_KEY_ID")
        sk = settings.AWS_SECRET_ACCESS_KEY or os.environ.get("AWS_SECRET_ACCESS_KEY")
        st = settings.AWS_SESSION_TOKEN or os.environ.get("AWS_SESSION_TOKEN")

        if ak and sk:
            return boto3.Session(
                aws_access_key_id=ak,
                aws_secret_access_key=sk,
                aws_session_token=st,
                region_name=settings.AWS_REGION,
            )
        return boto3.Session(region_name=settings.AWS_REGION)

    @classmethod
    def get_client(
        cls,
        service_name: str,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> Any:
        """Create a configured boto3 client for the requested service with role assumption if needed."""
        session = cls.create_boto3_session()
        settings = get_settings()
        role_arn = settings.AWS_ROLE_ARN or os.environ.get("AWS_ROLE_ARN")
        boto_cfg = cls.get_botocore_config(timeout=timeout, max_retries=max_retries)

        if role_arn:
            try:
                sts_client = session.client("sts", config=boto_cfg)
                assumed_role = sts_client.assume_role(
                    RoleArn=role_arn,
                    RoleSessionName="LifeThreadSession",
                )
                creds = assumed_role["Credentials"]
                import boto3

                return boto3.client(
                    service_name,
                    aws_access_key_id=creds["AccessKeyId"],
                    aws_secret_access_key=creds["SecretAccessKey"],
                    aws_session_token=creds["SessionToken"],
                    region_name=settings.AWS_REGION,
                    config=boto_cfg,
                )
            except Exception as e:
                logger.warning("STS Role assumption failed for %s, falling back to default session: %s", role_arn, e)

        return session.client(service_name, config=boto_cfg)

    @classmethod
    def is_aws_available(cls) -> bool:
        """Check if AWS credentials or IAM identity appear present in the environment."""
        settings = get_settings()
        ak = settings.AWS_ACCESS_KEY_ID or os.environ.get("AWS_ACCESS_KEY_ID")
        role = settings.AWS_ROLE_ARN or os.environ.get("AWS_ROLE_ARN")
        has_profile = bool(os.environ.get("AWS_PROFILE"))
        # In AWS environments (EC2, ECS, EKS, Lambda), credentials can also be retrieved from instance metadata
        has_container = bool(os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"))
        has_web_identity = bool(os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE"))
        return bool(ak or role or has_profile or has_container or has_web_identity)
