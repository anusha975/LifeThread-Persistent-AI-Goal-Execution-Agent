class DocumentProcessingError(Exception):
    """Base exception for document intelligence pipeline errors."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.original_error = original_error


class DocumentValidationError(DocumentProcessingError):
    """Exception raised when document validation (size, type, header) fails."""

    pass


class DocumentExtractionError(DocumentProcessingError):
    """Exception raised when extracting text content from document fails."""

    pass


class DocumentDuplicateError(DocumentProcessingError):
    """Exception raised when an identical document has already been ingested for user."""

    def __init__(self, message: str, existing_document_id: str | None = None) -> None:
        super().__init__(message)
        self.existing_document_id = existing_document_id
