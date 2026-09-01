"""Contract classification and summary generation engine."""

import json
import re

import structlog

from termnova.config import Settings
from termnova.llm_client import acompletion_with_fallback, provider_available
from termnova.triage.schemas import ClassificationResult

logger = structlog.get_logger(__name__)

CONTRACT_TYPES = [
    "msa",
    "nda",
    "sow",
    "amendment",
    "lease",
    "employment",
    "vendor",
    "services",
    "license",
    "other",
]


class ContractClassifier:
    """Classifies contract type and extracts executive summary bullets."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def classify(self, document_text: str, filename: str) -> ClassificationResult:
        """
        Classify contract type, compute confidence, and generate summary bullets.

        Strategy:
        1. Filename heuristic check
        2. First-page text header pattern check
        3. LLM structured analysis for deep summary bullets, dates, value, and risk signals
        """
        fn_type, fn_conf = self._classify_by_filename(filename)
        text_type, text_conf = self._classify_by_text(document_text)

        # Combine heuristic signals
        if fn_conf >= 0.8:
            detected_type = fn_type
            confidence = fn_conf
        elif text_conf >= 0.8:
            detected_type = text_type
            confidence = text_conf
        elif fn_conf > 0.4:
            detected_type = fn_type
            confidence = 0.65
        else:
            detected_type = text_type if text_type != "other" else "other"
            confidence = max(fn_conf, text_conf, 0.5)

        # Extract dates, values, and risk signals heuristically
        detected_dates = self._extract_dates_heuristic(document_text)
        detected_value = self._extract_value_heuristic(document_text)
        risk_signals = self._extract_risk_signals_heuristic(document_text)

        # Generate summary bullets
        has_credentials = provider_available(
            self.settings.LLM_PROVIDER, self.settings
        ) or provider_available(self.settings.LLM_FALLBACK_PROVIDER, self.settings)
        if has_credentials:
            try:
                llm_result = await self._classify_by_llm(
                    document_text[:4000], filename, detected_type
                )
                return llm_result
            except Exception as e:
                logger.warning(
                    "LLM triage classification failed, falling back to heuristics", error=str(e)
                )

        summary_bullets = self._generate_heuristic_summary(
            filename=filename,
            contract_type=detected_type,
            detected_value=detected_value,
            detected_dates=detected_dates,
            risk_signals=risk_signals,
            text_snippet=document_text[:2000],
        )

        action_required = self._suggest_action(detected_type, risk_signals, detected_value)

        return ClassificationResult(
            contract_type=detected_type,
            confidence=confidence,
            summary_bullets=summary_bullets,
            action_required=action_required,
            detected_dates=detected_dates,
            detected_value=detected_value,
            risk_signals=risk_signals,
        )

    def _classify_by_filename(self, filename: str) -> tuple[str, float]:
        """Fast heuristic classification from filename patterns."""
        fn = filename.lower()
        patterns = {
            "nda": (["nda", "non-disclosure", "confidentiality", "secrecy"], 0.90),
            "sow": (["sow", "statement of work", "statement_of_work", "scope of work"], 0.90),
            "msa": (["msa", "master service", "master_agreement", "master services"], 0.90),
            "amendment": (["amendment", "addendum", "modification", "annex"], 0.85),
            "lease": (["lease", "rental", "tenancy", "sublease"], 0.85),
            "employment": (
                ["employment", "offer letter", "consulting agreement", "contractor"],
                0.85,
            ),
            "vendor": (["vendor", "supplier", "procurement", "purchase agreement"], 0.80),
            "license": (["license", "eula", "saas agreement", "software license"], 0.80),
            "services": (["services agreement", "service agreement", "sla"], 0.80),
        }
        for contract_type, (keywords, confidence) in patterns.items():
            if any(kw in fn for kw in keywords):
                return contract_type, confidence
        return "other", 0.3

    def _classify_by_text(self, text: str) -> tuple[str, float]:
        """Heuristic classification from document title page text."""
        snippet = text[:2000].lower()
        patterns = {
            "nda": (
                [
                    "non-disclosure agreement",
                    "mutual confidentiality agreement",
                    "confidentiality agreement",
                ],
                0.90,
            ),
            "msa": (
                ["master services agreement", "master service agreement", "master agreement"],
                0.90,
            ),
            "sow": (["statement of work", "scope of work", "schedule a - statement of work"], 0.90),
            "amendment": (
                ["amendment to", "amendment no", "first amendment", "second amendment"],
                0.85,
            ),
            "lease": (["commercial lease agreement", "lease agreement", "premises lease"], 0.85),
            "employment": (
                ["employment agreement", "executive employment", "offer of employment"],
                0.85,
            ),
            "vendor": (["vendor agreement", "master supplier agreement", "supplier terms"], 0.80),
            "license": (
                ["software license agreement", "end user license", "software as a service"],
                0.80,
            ),
            "services": (
                ["professional services agreement", "consulting services agreement"],
                0.80,
            ),
        }
        for contract_type, (keywords, confidence) in patterns.items():
            if any(kw in snippet for kw in keywords):
                return contract_type, confidence
        return "other", 0.3

    def _extract_dates_heuristic(self, text: str) -> dict[str, str | None]:
        """Extract key dates (effective, expiration, notice)."""
        snippet = text[:3000]
        dates: dict[str, str | None] = {
            "effective_date": None,
            "expiration_date": None,
            "notice_deadline": None,
        }

        # Effective date pattern
        eff_match = re.search(
            r"(?:effective|dated|commencing)\s+(?:as\s+of\s+)?([A-Z][a-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
            snippet,
            re.IGNORECASE,
        )
        if eff_match:
            dates["effective_date"] = eff_match.group(1)

        # Expiration / Term pattern
        exp_match = re.search(
            r"(?:expire|terminat|end)\s+(?:on|as of)\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
            snippet,
            re.IGNORECASE,
        )
        if exp_match:
            dates["expiration_date"] = exp_match.group(1)

        # Notice period
        notice_match = re.search(
            r"(\d{1,3})[\s-]day\s+(?:written\s+)?notice", snippet, re.IGNORECASE
        )
        if notice_match:
            dates["notice_deadline"] = f"{notice_match.group(1)} days notice required"

        return dates

    def _extract_value_heuristic(self, text: str) -> float | None:
        """Extract contract dollar amounts."""
        snippet = text[:4000]
        val_matches = re.findall(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)", snippet)
        amounts: list[float] = []
        for v in val_matches:
            try:
                amt = float(v.replace(",", ""))
                if amt > 100:  # Skip trivial fees
                    amounts.append(amt)
            except ValueError:
                continue
        return max(amounts) if amounts else None

    def _extract_risk_signals_heuristic(self, text: str) -> list[str]:
        """Identify common risk signals in legal text."""
        snippet = text[:5000].lower()
        signals: list[str] = []

        if (
            "uncapped liability" in snippet
            or "unlimited liability" in snippet
            or "liability shall not be limited" in snippet
        ):
            signals.append("uncapped_liability")
        if (
            "auto-renew" in snippet
            or "automatic renewal" in snippet
            or "automatically renew" in snippet
        ):
            signals.append("auto_renewal")
        if "indemnify" in snippet or "hold harmless" in snippet or "indemnification" in snippet:
            signals.append("broad_indemnity")
        if "non-compete" in snippet or "exclusivity" in snippet or "exclusive dealing" in snippet:
            signals.append("exclusivity_clause")
        if "data protection" in snippet or "gdpr" in snippet or "security breach" in snippet:
            signals.append("data_security_compliance")
        if "termination for convenience" in snippet:
            signals.append("termination_convenience")

        return signals

    def _generate_heuristic_summary(
        self,
        filename: str,
        contract_type: str,
        detected_value: float | None,
        detected_dates: dict[str, str | None],
        risk_signals: list[str],
        text_snippet: str,
    ) -> list[str]:
        """Produce 3-5 concise bullet points summarizing the contract."""
        clean_fn = re.sub(r"^[0-9a-fA-F]{8}_", "", filename)
        clean_fn = re.sub(r"_\d{4}_EX_\d+[\.\d]*_", " ", clean_fn)
        clean_fn = clean_fn.replace("__", " ").replace("_", " ").strip()

        bullets = [
            f"Agreement classified as **{contract_type.upper()}** ({clean_fn})",
        ]

        if detected_value:
            bullets.append(f"Estimated contract value: **${detected_value:,.2f} USD**")

        if detected_dates.get("effective_date"):
            bullets.append(f"Effective date: {detected_dates['effective_date']}")
        if detected_dates.get("expiration_date"):
            bullets.append(f"Expiration / Renewal date: {detected_dates['expiration_date']}")
        if detected_dates.get("notice_deadline"):
            bullets.append(f"Termination notice requirement: {detected_dates['notice_deadline']}")

        if risk_signals:
            formatted_risks = ", ".join(r.replace("_", " ").title() for r in risk_signals[:3])
            bullets.append(f"Noted risk considerations: {formatted_risks}")
        else:
            bullets.append(
                "Standard legal terms with no overt liability flags detected in preliminary triage."
            )

        return bullets[:5]

    def _suggest_action(
        self, contract_type: str, risk_signals: list[str], detected_value: float | None
    ) -> str:
        """Determine recommended reviewer action."""
        if "uncapped_liability" in risk_signals or (detected_value and detected_value >= 1_000_000):
            return "Escalate to Senior Legal Counsel for liability and financial review"
        if contract_type == "nda":
            return "Standard NDA — candidate for fast-track approval"
        if contract_type in ["msa", "vendor"]:
            return "Review standard terms, payment milestones, and SLA guarantees"
        if contract_type == "amendment":
            return "Cross-reference with master agreement terms before execution"
        return "Review agreement terms and assign reviewer"

    async def _classify_by_llm(
        self, text_snippet: str, filename: str, heuristic_type: str
    ) -> ClassificationResult:
        """Call litellm with structured prompt for detailed triage classification."""
        prompt = f"""You are an expert legal AI reviewing incoming contracts for automated triage.
Analyze the following document excerpt and return a JSON object with:
- "contract_type": one of ["msa", "nda", "sow", "amendment", "lease", "employment", "vendor", "services", "license", "other"]
- "confidence": float between 0.0 and 1.0
- "summary_bullets": array of 3 to 5 concise executive bullet points
- "action_required": one sentence describing the recommended next action
- "detected_value": float or null (total contract value if stated)
- "detected_dates": object with keys "effective_date", "expiration_date", "notice_deadline"
- "risk_signals": array of strings (e.g. "uncapped_liability", "auto_renewal", "broad_indemnity", "strict_sla")

Filename: {filename}
Preliminary heuristic guess: {heuristic_type}

Document Excerpt:
{text_snippet}

Respond ONLY with a valid JSON object matching this schema.
"""
        response = await acompletion_with_fallback(
            messages=[{"role": "user", "content": prompt}],
            settings=self.settings,
            temperature=0.1,
            max_tokens=800,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n", "", content)
            content = re.sub(r"\n```$", "", content)

        data = json.loads(content)
        return ClassificationResult(
            contract_type=data.get("contract_type", heuristic_type),
            confidence=float(data.get("confidence", 0.9)),
            summary_bullets=data.get("summary_bullets", []),
            action_required=data.get("action_required", "Review agreement"),
            detected_dates=data.get("detected_dates", {}),
            detected_value=data.get("detected_value"),
            risk_signals=data.get("risk_signals", []),
        )
