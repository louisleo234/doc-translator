"""Application configuration from environment variables."""
import os
from dataclasses import dataclass
from typing import List


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


@dataclass
class AppConfig:
    """
    Deploy-time configuration loaded from environment variables.

    Attributes:
        jwt_secret: JWT signing key (required)
        s3_bucket: S3 bucket name for file storage (required)
        max_concurrent_files: Max parallel file processing
        translation_batch_size: Cells/paragraphs per Bedrock API call
        max_batch_concurrency: Max concurrent batch API calls per file
        max_file_size: Max upload size in bytes (200MB default)
        max_term_length: Max character length of a terminology term
        max_terms_for_translation: Max term pairs queried for injection
        allowed_extensions: List of allowed file extensions
    """
    jwt_secret: str
    s3_bucket: str
    max_concurrent_files: int
    translation_batch_size: int
    max_batch_concurrency: int
    max_file_size: int
    max_term_length: int
    max_terms_for_translation: int
    allowed_extensions: List[str]

    @classmethod
    def from_env(cls) -> "AppConfig":
        """
        Load configuration from environment variables.

        Required:
            JWT_SECRET: JWT signing key
            S3_BUCKET: S3 bucket name for file storage

        Optional (with defaults):
            MAX_CONCURRENT_FILES: 5
            TRANSLATION_BATCH_SIZE: 20
            MAX_FILE_SIZE: 209715200 (200MB)

        Note: Default values are mirrored in ecs/cdk.json for CDK/ECS deployments.

        Raises:
            ConfigurationError: If required vars missing or validation fails
        """
        errors = []

        # Required
        jwt_secret = os.environ.get("JWT_SECRET")
        if not jwt_secret:
            errors.append("JWT_SECRET environment variable is required")

        s3_bucket = os.environ.get("S3_BUCKET")
        if not s3_bucket:
            errors.append("S3_BUCKET environment variable is required")

        # Optional with validation
        max_files = os.getenv("MAX_CONCURRENT_FILES", "5")
        if not max_files.isdigit() or int(max_files) < 1:
            errors.append("MAX_CONCURRENT_FILES must be a positive integer")

        batch_size = os.getenv("TRANSLATION_BATCH_SIZE", "20")
        if not batch_size.isdigit() or int(batch_size) < 1:
            errors.append("TRANSLATION_BATCH_SIZE must be a positive integer")

        max_file_size = os.getenv("MAX_FILE_SIZE", "209715200")
        # NOTE: MAX_FILE_SIZE should be set based on available memory. Large
        # files produce many in-memory segments during translation (segment
        # list + results array), so ensure the deployment has sufficient RAM.
        if not max_file_size.isdigit() or int(max_file_size) < 1:
            errors.append("MAX_FILE_SIZE must be a positive integer")

        max_batch_concurrency = os.getenv("MAX_BATCH_CONCURRENCY", "3")
        if (
            not max_batch_concurrency.isdigit()
            or int(max_batch_concurrency) < 1
            or int(max_batch_concurrency) > 20
        ):
            errors.append(
                "MAX_BATCH_CONCURRENCY must be a positive integer (1-20)"
            )

        max_term_length = os.getenv("MAX_TERM_LENGTH", "500")
        if not max_term_length.isdigit() or int(max_term_length) < 1:
            errors.append("MAX_TERM_LENGTH must be a positive integer")

        max_terms_for_translation = os.getenv("MAX_TERMS_FOR_TRANSLATION", "5000")
        if not max_terms_for_translation.isdigit() or int(max_terms_for_translation) < 1:
            errors.append("MAX_TERMS_FOR_TRANSLATION must be a positive integer")

        if errors:
            raise ConfigurationError("\n".join(errors))

        return cls(
            jwt_secret=jwt_secret,
            s3_bucket=s3_bucket,
            max_concurrent_files=int(max_files),
            translation_batch_size=int(batch_size),
            max_batch_concurrency=int(max_batch_concurrency),
            max_file_size=int(max_file_size),
            max_term_length=int(max_term_length),
            max_terms_for_translation=int(max_terms_for_translation),
            allowed_extensions=[".xlsx", ".docx", ".pptx", ".pdf", ".txt", ".md"],
        )
