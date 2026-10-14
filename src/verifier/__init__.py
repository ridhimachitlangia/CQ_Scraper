"""Contact deliverability and verification engine (Phase 5).

Provides:
- EmailSyntaxValidator, SyntaxCheckResult (Task 5.1)
- DNSMXResolver, MXResolutionResult, MXRecord (Task 5.2)
- SMTPHandshakeVerifier, SMTPHandshakeResult (Task 5.3)
- SocialProfileValidator, SocialValidationResult (Task 5.4)
- ContactVerifier, VerificationResult (Task 5.5)
"""

from src.verifier.syntax_check import EmailSyntaxValidator, SyntaxCheckResult
from src.verifier.mx_resolver import DNSMXResolver, MXResolutionResult, MXRecord
from src.verifier.smtp_handshake import SMTPHandshakeVerifier, SMTPHandshakeResult
from src.verifier.social_validator import SocialProfileValidator, SocialValidationResult
from src.verifier.contact_verifier import ContactVerifier, VerificationResult

__all__ = [
    "EmailSyntaxValidator",
    "SyntaxCheckResult",
    "DNSMXResolver",
    "MXResolutionResult",
    "MXRecord",
    "SMTPHandshakeVerifier",
    "SMTPHandshakeResult",
    "SocialProfileValidator",
    "SocialValidationResult",
    "ContactVerifier",
    "VerificationResult",
]
