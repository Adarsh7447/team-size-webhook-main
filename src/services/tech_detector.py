"""
Technology detector service for identifying CRMs and tools on websites.

Detects various real estate CRMs and marketing tools from HTML content.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Pattern

from src.core.logging import get_logger
from src.schemas.internal import TechnologyInfo

logger = get_logger("tech-detector")


@dataclass
class TechnologySignature:
    """Definition of a technology signature to detect."""

    name: str
    patterns: List[str]
    compiled_patterns: List[Pattern] = field(default_factory=list, init=False)

    def __post_init__(self):
        """Compile regex patterns for efficiency."""
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.patterns
        ]


class TechnologyDetector:
    """
    Service for detecting technologies used on real estate websites.

    Identifies CRMs, website platforms, and marketing tools.

    Usage:
        detector = TechnologyDetector()
        info = detector.detect(html_content)
    """

    # CRM signatures
    CRM_SIGNATURES = [
        TechnologySignature(
            name="Follow Up Boss",
            patterns=[r"\bfollowupboss\.com", r"window\.FUB", r"fub\.com"],
        ),
        TechnologySignature(
            name="KVCore",
            patterns=[r"\bkvcore\.com", r"window\.kvCore", r"kvcoreidx"],
        ),
        TechnologySignature(
            name="Ylopo",
            patterns=[r"\bylopo\.com", r"window\.YLOPO", r"ylopo-"],
        ),
        TechnologySignature(
            name="BoomTown",
            patterns=[r"\bboomtownroi\.com", r"boomtown\.com", r"window\.BoomTown"],
        ),
        TechnologySignature(
            name="Chime",
            patterns=[r"\bchime\.me", r"chimeinc\.com", r"window\.Chime"],
        ),
        TechnologySignature(
            name="LionDesk",
            patterns=[r"\bliondesk\.com", r"window\.LionDesk"],
        ),
        TechnologySignature(
            name="Real Geeks",
            patterns=[r"\brealgeeks\.com", r"realgeeksidx"],
        ),
        TechnologySignature(
            name="Sierra Interactive",
            patterns=[r"\bsierrainteractive\.com", r"sierra-interactive"],
        ),
        TechnologySignature(
            name="Cinc",
            patterns=[r"\bcinc\.com", r"cincpro\.com", r"window\.CINC"],
        ),
        TechnologySignature(
            name="IXACT Contact",
            patterns=[r"\bixactcontact\.com", r"ixact\.com"],
        ),
        TechnologySignature(
            name="Propertybase",
            patterns=[r"\bpropertybase\.com", r"window\.Propertybase"],
        ),
        TechnologySignature(
            name="Wise Agent",
            patterns=[r"\bwiseagent\.com", r"wise-agent"],
        ),
        TechnologySignature(
            name="Top Producer",
            patterns=[r"\btopproducer\.com", r"top-producer"],
        ),
    ]

    # Website platform signatures
    PLATFORM_SIGNATURES = [
        TechnologySignature(
            name="WordPress",
            patterns=[r"\bwp-content\b", r"\bwp-includes\b", r"wordpress\.org"],
        ),
        TechnologySignature(
            name="Squarespace",
            patterns=[r"\bsquarespace\.com", r"squarespace-cdn", r"static1\.squarespace"],
        ),
        TechnologySignature(
            name="Wix",
            patterns=[r"\bwix\.com", r"wixstatic\.com", r"_wix_browser_sess"],
        ),
        TechnologySignature(
            name="Placester",
            patterns=[r"\bplacester\.com", r"placester-theme"],
        ),
        TechnologySignature(
            name="Agent Image",
            patterns=[r"\bagentimage\.com", r"agent-image"],
        ),
        TechnologySignature(
            name="IDX Broker",
            patterns=[r"\bidxbroker\.com", r"idx-broker"],
        ),
        TechnologySignature(
            name="Showcase IDX",
            patterns=[r"\bshowcaseidx\.com", r"showcase-idx"],
        ),
    ]

    # Email marketing tool signatures
    EMAIL_TOOL_SIGNATURES = [
        TechnologySignature(
            name="Mailchimp",
            patterns=[r"\bmailchimp\.com", r"mc\.us\d+\.list-manage"],
        ),
        TechnologySignature(
            name="Constant Contact",
            patterns=[r"\bconstantcontact\.com", r"cc\.constantcontact"],
        ),
        TechnologySignature(
            name="ActiveCampaign",
            patterns=[r"\bactivecampaign\.com", r"activehosted\.com"],
        ),
        TechnologySignature(
            name="HubSpot",
            patterns=[r"\bhubspot\.com", r"hs-scripts\.com", r"hsforms\.net"],
        ),
    ]

    def detect(self, html: str) -> TechnologyInfo:
        """
        Detect technologies from HTML content.

        Args:
            html: HTML content to analyze

        Returns:
            TechnologyInfo with detected CRMs and email tools
        """
        if not html:
            return TechnologyInfo(
                detected_crms=["Not Found"],
                detected_email_tools=["Not Found"],
            )

        detected_crms = self._detect_signatures(html, self.CRM_SIGNATURES)
        detected_email_tools = self._detect_signatures(html, self.EMAIL_TOOL_SIGNATURES)

        # If nothing found, return "Not Found"
        if not detected_crms:
            detected_crms = ["Not Found"]
        if not detected_email_tools:
            detected_email_tools = ["Not Found"]

        logger.debug(
            "Technology detection complete",
            crms=detected_crms,
            email_tools=detected_email_tools,
        )

        return TechnologyInfo(
            detected_crms=detected_crms,
            detected_email_tools=detected_email_tools,
        )

    def detect_crms(self, html: str) -> List[str]:
        """
        Detect only CRM systems from HTML content.

        Args:
            html: HTML content to analyze

        Returns:
            List of detected CRM names
        """
        if not html:
            return ["Not Found"]

        detected = self._detect_signatures(html, self.CRM_SIGNATURES)
        return detected if detected else ["Not Found"]

    def detect_platforms(self, html: str) -> List[str]:
        """
        Detect website platforms from HTML content.

        Args:
            html: HTML content to analyze

        Returns:
            List of detected platform names
        """
        if not html:
            return ["Not Found"]

        detected = self._detect_signatures(html, self.PLATFORM_SIGNATURES)
        return detected if detected else ["Not Found"]

    def detect_all(self, html: str) -> Dict[str, List[str]]:
        """
        Detect all technology categories from HTML content.

        Args:
            html: HTML content to analyze

        Returns:
            Dictionary with 'crms', 'platforms', and 'email_tools' keys
        """
        if not html:
            return {
                "crms": ["Not Found"],
                "platforms": ["Not Found"],
                "email_tools": ["Not Found"],
            }

        return {
            "crms": self._detect_signatures(html, self.CRM_SIGNATURES) or ["Not Found"],
            "platforms": self._detect_signatures(html, self.PLATFORM_SIGNATURES) or ["Not Found"],
            "email_tools": self._detect_signatures(html, self.EMAIL_TOOL_SIGNATURES) or ["Not Found"],
        }

    def _detect_signatures(
        self,
        html: str,
        signatures: List[TechnologySignature],
    ) -> List[str]:
        """
        Detect technologies matching the given signatures.

        Args:
            html: HTML content to search
            signatures: List of technology signatures to match

        Returns:
            List of detected technology names
        """
        detected = []

        for signature in signatures:
            for pattern in signature.compiled_patterns:
                if pattern.search(html):
                    detected.append(signature.name)
                    break  # Found this tech, move to next

        return detected


# Global instance for convenience
tech_detector = TechnologyDetector()
