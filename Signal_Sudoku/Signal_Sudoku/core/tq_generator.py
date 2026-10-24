"""Technical Query (TQ) generator for Signal Sudoku.

Generates structured TQs for unresolved allocation issues
that require engineering decisions.
"""
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class TechnicalQuery:
    """A single Technical Query raised during allocation or validation.

    Attributes:
        tq_id: Unique identifier in the form ``TQ-XXXX``.
        affected_item: The signal tag or hardware ID this TQ relates to.
        category: Classification of the issue – one of ``'missing_subtype'``,
            ``'capacity'``, ``'segregation'``, ``'cable_info'``, ``'naming'``,
            ``'mapping'``.
        description: Human-readable summary of the issue.
        reason: Why this TQ was raised.
        information_needed: What additional information is required.
        suggested_action: Recommended resolution steps.
        status: Workflow status – ``'Open'``, ``'Closed'``, etc.
        created_date: ISO-format timestamp when the TQ was generated.
        priority: ``'High'``, ``'Medium'``, or ``'Low'``.
    """
    tq_id: str
    affected_item: str
    category: str
    description: str
    reason: str
    information_needed: str
    suggested_action: str
    status: str = 'Open'
    created_date: str = ''
    priority: str = 'Medium'


class TQGenerator:
    """Creates and manages Technical Queries for allocation issues.

    TQ IDs are auto-incremented from ``TQ-0001``.
    """

    # Map validation-finding severities / categories to TQ priority
    _SEVERITY_TO_PRIORITY = {
        'error': 'High',
        'warning': 'Medium',
        'info': 'Low',
    }

    def __init__(self) -> None:
        """Initialise the TQ generator with a fresh sequence counter."""
        self._next_id: int = 1

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_id(self) -> str:
        """Generate the next sequential TQ ID and advance the counter."""
        tq_id = f'TQ-{self._next_id:04d}'
        self._next_id += 1
        return tq_id

    def _now_iso(self) -> str:
        """Return the current UTC time as an ISO-8601 string."""
        return datetime.utcnow().isoformat(timespec='seconds')

    # ------------------------------------------------------------------
    # Public API – generate from validation findings
    # ------------------------------------------------------------------

    def generate_from_validation(
        self,
        validation_findings: list,
    ) -> list[TechnicalQuery]:
        """Convert relevant validation findings into Technical Queries.

        Only findings with severity ``'error'`` or those whose category
        typically requires engineering input are converted.  ``'info'``-level
        findings about optional missing fields are skipped.

        Args:
            validation_findings: A list of objects that expose at least the
                attributes ``severity``, ``category``, ``tag``, ``message``,
                and ``suggestion``.

        Returns:
            A list of :class:`TechnicalQuery` objects.
        """
        tqs: list[TechnicalQuery] = []

        # Categories that always warrant a TQ
        tq_categories = {
            'missing_data',
            'duplicate',
            'invalid_value',
            'segregation',
            'capacity',
            'mapping',
        }

        for finding in validation_findings:
            severity = getattr(finding, 'severity', 'info')
            category = getattr(finding, 'category', '')

            # Skip low-severity findings that don't need engineering input
            if severity == 'info' and category not in tq_categories:
                continue

            tq = TechnicalQuery(
                tq_id=self._make_id(),
                affected_item=getattr(finding, 'tag', '') or getattr(finding, 'affected_item', 'Unknown'),
                category=self._map_category(category),
                description=getattr(finding, 'message', str(finding)),
                reason=f"Validation finding ({severity}): {getattr(finding, 'message', '')}",
                information_needed=getattr(finding, 'suggestion', '')
                    or 'Please review and provide the required information.',
                suggested_action=getattr(finding, 'suggestion', '')
                    or 'Review the finding and update the input data accordingly.',
                status='Open',
                created_date=self._now_iso(),
                priority=self._SEVERITY_TO_PRIORITY.get(severity, 'Medium'),
            )
            tqs.append(tq)

        return tqs

    # ------------------------------------------------------------------
    # Public API – generate specific TQ types
    # ------------------------------------------------------------------

    def generate_capacity_tq(self, signal, reason: str) -> TechnicalQuery:
        """Generate a TQ for a capacity-related allocation failure.

        Args:
            signal: A signal object (must have a ``tag`` attribute).
            reason: Description of why the signal could not be allocated.

        Returns:
            A new :class:`TechnicalQuery`.
        """
        tag = getattr(signal, 'tag', str(signal))
        return TechnicalQuery(
            tq_id=self._make_id(),
            affected_item=tag,
            category='capacity',
            description=f"Signal '{tag}' could not be allocated due to capacity constraints.",
            reason=reason,
            information_needed='Confirm whether additional hardware (cabinet / CIOC / baseplate) can be provisioned.',
            suggested_action='Increase hardware capacity or re-prioritise signals.',
            status='Open',
            created_date=self._now_iso(),
            priority='High',
        )

    def generate_missing_info_tq(self, signal, missing_field: str) -> TechnicalQuery:
        """Generate a TQ for missing signal information.

        Args:
            signal: A signal object (must have a ``tag`` attribute).
            missing_field: Name of the field that is missing or incomplete.

        Returns:
            A new :class:`TechnicalQuery`.
        """
        tag = getattr(signal, 'tag', str(signal))
        return TechnicalQuery(
            tq_id=self._make_id(),
            affected_item=tag,
            category='missing_subtype' if missing_field.lower() in ('do_subtype', 'subtype') else 'cable_info',
            description=f"Signal '{tag}' is missing required field '{missing_field}'.",
            reason=f"The field '{missing_field}' was not provided in the input data.",
            information_needed=f"Please supply the '{missing_field}' value for signal '{tag}'.",
            suggested_action=f"Update the I/O MDB to include '{missing_field}' for this signal.",
            status='Open',
            created_date=self._now_iso(),
            priority='Medium',
        )

    def generate_segregation_tq(self, signal, conflict_description: str) -> TechnicalQuery:
        """Generate a TQ for a segregation conflict.

        Args:
            signal: A signal object (must have a ``tag`` attribute).
            conflict_description: What the segregation conflict is.

        Returns:
            A new :class:`TechnicalQuery`.
        """
        tag = getattr(signal, 'tag', str(signal))
        return TechnicalQuery(
            tq_id=self._make_id(),
            affected_item=tag,
            category='segregation',
            description=f"Segregation conflict for signal '{tag}': {conflict_description}",
            reason=conflict_description,
            information_needed='Confirm the correct segregation class assignment for this signal.',
            suggested_action='Review and correct the segregation assignment in the I/O MDB.',
            status='Open',
            created_date=self._now_iso(),
            priority='High',
        )

    def generate_mapping_tq(self, signal, issue: str) -> TechnicalQuery:
        """Generate a TQ for a signal-to-hardware mapping issue.

        Args:
            signal: A signal object (must have a ``tag`` attribute).
            issue: Description of the mapping problem.

        Returns:
            A new :class:`TechnicalQuery`.
        """
        tag = getattr(signal, 'tag', str(signal))
        return TechnicalQuery(
            tq_id=self._make_id(),
            affected_item=tag,
            category='mapping',
            description=f"Mapping issue for signal '{tag}': {issue}",
            reason=issue,
            information_needed='Confirm the correct CHARM type and terminal block for this signal.',
            suggested_action='Update the classification mapping or provide additional signal details.',
            status='Open',
            created_date=self._now_iso(),
            priority='Medium',
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_summary(self, tqs: list[TechnicalQuery]) -> dict:
        """Produce a summary breakdown of a list of TQs.

        Args:
            tqs: The list of :class:`TechnicalQuery` objects to summarise.

        Returns:
            A dict with keys ``total``, ``by_category``, ``by_priority``,
            and ``by_status`` (each a dict of counts).
        """
        by_category: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        by_status: dict[str, int] = {}

        for tq in tqs:
            by_category[tq.category] = by_category.get(tq.category, 0) + 1
            by_priority[tq.priority] = by_priority.get(tq.priority, 0) + 1
            by_status[tq.status] = by_status.get(tq.status, 0) + 1

        return {
            'total': len(tqs),
            'by_category': by_category,
            'by_priority': by_priority,
            'by_status': by_status,
        }

    # ------------------------------------------------------------------
    # Internal category mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _map_category(validation_category: str) -> str:
        """Map a validation-finding category to a TQ category string."""
        mapping = {
            'missing_data': 'cable_info',
            'duplicate': 'naming',
            'invalid_value': 'mapping',
            'segregation': 'segregation',
            'capacity': 'capacity',
            'mapping': 'mapping',
        }
        return mapping.get(validation_category, 'mapping')
