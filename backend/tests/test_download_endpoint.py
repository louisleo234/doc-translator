"""
Tests for the file download endpoint.

The download endpoint returns a presigned S3 URL for direct browser download.
"""
import pytest
import sys
from pathlib import Path
from starlette.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock
import tempfile

# Add backend directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import main
from main import app, AppContext


@pytest.fixture
def client():
    """Create a test client with initialized app context."""
    with patch('main.AppConfig') as mock_config, \
         patch('main.AuthService') as mock_auth, \
         patch('main.S3FileStorage') as mock_s3_storage, \
         patch('main.JobStore'), \
         patch('main.TranslationService'), \
         patch('main.ExcelProcessor'), \
         patch('main.ConcurrentExecutor'), \
         patch('main.TranslationOrchestrator'), \
         patch('main.JobManager'), \
         patch('main.DynamoDBRepository'), \
         patch('main.UserService'), \
         patch('main.ThesaurusService'), \
         patch('main.GlobalConfigService'), \
         patch('main.LanguagePairService'), \
         patch('main.UserSettingsService'), \
         patch('main.JobRepository'):

        # Mock app config
        mock_config_instance = Mock()
        mock_config_instance.jwt_secret = "test-secret"
        mock_config_instance.s3_bucket = "test-bucket"
        mock_config_instance.max_concurrent_files = 10
        mock_config_instance.translation_batch_size = 10
        mock_config_instance.max_file_size = 52428800
        mock_config_instance.allowed_extensions = [".xlsx", ".docx", ".pptx", ".pdf"]
        mock_config.from_env.return_value = mock_config_instance

        # Mock auth service
        mock_auth_instance = Mock()
        mock_auth_instance.verify_token.return_value = {"sub": "testuser", "username": "testuser"}
        mock_auth.return_value = mock_auth_instance

        # Mock S3 file storage
        mock_s3_instance = Mock()
        mock_s3_instance.generate_output_download_url = AsyncMock(
            return_value="https://s3.amazonaws.com/test-bucket/fake-presigned-url"
        )
        mock_s3_storage.return_value = mock_s3_instance

        # Initialize app context
        main.app_context = AppContext()

        # Override services with our mocks
        main.app_context.auth_service = mock_auth_instance
        main.app_context.s3_file_storage = mock_s3_instance

        # Create and return test client
        client = TestClient(app)
        yield client

        # Cleanup
        main.app_context = None


@pytest.fixture
def auth_token():
    """Get a test authentication token."""
    return "test-token-123"


def test_download_file_success(client, auth_token):
    """Test successful file download returns presigned URL."""
    job_id = "test-job-123"
    filename = "test_file_vi.xlsx"

    response = client.get(
        f"/api/download?job_id={job_id}&filename={filename}",
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert "url" in data
    assert "fake-presigned-url" in data["url"]

    # Verify S3 generate_output_download_url was called with correct args
    main.app_context.s3_file_storage.generate_output_download_url.assert_called_once_with(
        user_id="testuser",
        job_id=job_id,
        filename=filename,
    )


def test_download_file_missing_auth(client):
    """Test download without authentication."""
    response = client.get("/api/download?job_id=test-job&filename=test.xlsx")

    assert response.status_code == 401
    assert "Authentication required" in response.json()["error"]


def test_download_file_invalid_token(client):
    """Test download with invalid token."""
    # Mock the auth service to return None for invalid tokens
    main.app_context.auth_service.verify_token.return_value = None

    response = client.get(
        "/api/download?job_id=test-job&filename=test.xlsx",
        headers={"Authorization": "Bearer invalid-token"}
    )

    assert response.status_code == 401
    assert "Invalid or expired token" in response.json()["error"]

    # Reset mock for other tests
    main.app_context.auth_service.verify_token.return_value = {"sub": "testuser", "username": "testuser"}


def test_download_file_missing_params(client, auth_token):
    """Test download with missing parameters."""
    # Missing filename
    response = client.get(
        "/api/download?job_id=test-job",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 400
    assert "Missing job_id or filename parameter" in response.json()["error"]

    # Missing job_id
    response = client.get(
        "/api/download?filename=test.xlsx",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 400
    assert "Missing job_id or filename parameter" in response.json()["error"]


def test_download_file_s3_error(client, auth_token):
    """Test download when S3 returns an error."""
    main.app_context.s3_file_storage.generate_output_download_url = AsyncMock(
        side_effect=Exception("S3 service unavailable")
    )

    response = client.get(
        "/api/download?job_id=test-job&filename=test.xlsx",
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert response.status_code == 404
    assert "File not found or access denied" in response.json()["error"]


def test_download_file_uses_username_from_token(client, auth_token):
    """Test that download uses username from JWT token for S3 path."""
    # Reset the mock to track calls
    main.app_context.s3_file_storage.generate_output_download_url = AsyncMock(
        return_value="https://s3.amazonaws.com/test-bucket/presigned"
    )

    job_id = "job-456"
    filename = "document_vi.docx"

    response = client.get(
        f"/api/download?job_id={job_id}&filename={filename}",
        headers={"Authorization": f"Bearer {auth_token}"}
    )

    assert response.status_code == 200

    # Verify generate_output_download_url was called with the username from the token
    main.app_context.s3_file_storage.generate_output_download_url.assert_called_once_with(
        user_id="testuser",
        job_id=job_id,
        filename=filename,
    )
