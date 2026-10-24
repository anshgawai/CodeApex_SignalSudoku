"""Plain-English explanation helper for Technical Queries.

Maps TQ categories to jargon-free descriptions for hackathon judges and
first-time users.  Every explanation is derived from fields already present
on the TechnicalQuery dataclass — nothing is invented.
"""

from typing import Optional, Any
import re

# ---------------------------------------------------------------------------
# Category metadata
# ---------------------------------------------------------------------------

# NOTE (TQ Explanations): Category descriptions are concise single sentences per section
# (what_it_means, why_it_matters, corrective_action), eliminating redundant detail.
# Each entry: (plain_name, classification, what_it_means, why_it_matters, corrective_action)
_CATEGORY_INFO = {
    'missing_subtype': (
        'Missing Signal Subtype',
        'data_quality',
        'A signal is missing its hardware subtype needed to select the correct CHARM.',
        'A default hardware type may be assigned, which might not match the physical device.',
        'Specify the hardware subtype in the I/O Master Database.',
    ),
    'cable_info': (
        'Missing Signal Information',
        'data_quality',
        'A required signal field is missing or blank in the source data.',
        'Missing fields can prevent proper cable grouping and accurate hardware placement.',
        'Provide the missing field value in the I/O Master Database.',
    ),
    'capacity': (
        'Hardware Capacity Exceeded',
        'hard_constraint',
        'Available hardware slots are insufficient to place this signal under active rules.',
        'The signal cannot be allocated until additional hardware is provisioned or constraints are relaxed.',
        'Provision additional hardware capacity or review project spare rules.',
    ),
    'segregation': (
        'Segregation Conflict',
        'hard_constraint',
        'Signals of different segregation classes cannot share the same CIOC.',
        'Placing conflicting segregation classes together violates electrical safety standards.',
        'Correct segregation classes in source data or allocate additional CIOC hardware.',
    ),
    'naming': (
        'Duplicate or Invalid Tag',
        'data_quality',
        'Each signal must have a unique tag, but duplicate or invalid tags were detected.',
        'Duplicate tags cause ambiguity, preventing conflicting rows from being safely allocated.',
        'Rename or remove duplicate tags in the I/O Master Database.',
    ),
    'mapping': (
        'Signal-to-Hardware Mapping Issue',
        'preference_warning',
        'The signal I/O type could not be mapped to supported CHARM hardware.',
        'Without a valid hardware mapping, the signal cannot be allocated to a slot.',
        'Verify the I/O type in the source data or configure a classification mapping.',
    ),
}

# Classification labels for the UI
_CLASSIFICATION_LABELS = {
    'data_quality': '🔵 Data-Quality Error',
    'hard_constraint': '🔴 Hard Allocation Constraint',
    'preference_warning': '🟡 Preference / Warning',
}


def get_category_info(category: str) -> dict:
    """Return plain-English metadata for a TQ *category*.

    Returns a dict with keys ``plain_name``, ``classification``,
    ``classification_label``, ``what_it_means``, ``why_it_matters``,
    and ``corrective_action``.  If the category is unknown a generic
    fallback is returned.
    """
    info = _CATEGORY_INFO.get(category)
    if info is None:
        classification = 'preference_warning'
        return {
            'plain_name': category.replace('_', ' ').title(),
            'classification': classification,
            'classification_label': _CLASSIFICATION_LABELS.get(
                classification, classification
            ),
            'what_it_means': 'This issue was flagged during allocation processing.',
            'why_it_matters': 'This issue may affect signal placement or data completeness.',
            'corrective_action': 'Review the query details and update the source data or project rules.',
        }

    plain_name, classification, what_it_means, why_it_matters, corrective_action = info
    return {
        'plain_name': plain_name,
        'classification': classification,
        'classification_label': _CLASSIFICATION_LABELS.get(
            classification, classification
        ),
        'what_it_means': what_it_means,
        'why_it_matters': why_it_matters,
        'corrective_action': corrective_action,
    }


# NOTE (TQ Explanations - Allocation Status): Derive status strictly from actual application data
# (allocated_signals vs unallocated_signals). Never assume a signal is unallocated simply because it has a TQ.
def lookup_allocation_status(
    affected_item: str,
    allocation_result,
    tq: Optional[Any] = None,
) -> str:
    """Determine the actual allocation status of a signal tag.

    Returns one of ``'Allocated'``, ``'Unallocated'``, or
    ``'Unknown — signal not found in allocation data'``.
    """
    if allocation_result is None or affected_item is None or not affected_item.strip():
        return 'Unknown — allocation data not available'

    tag_clean = affected_item.strip()
    tag_lower = tag_clean.casefold()

    if tag_lower == 'unknown':
        for entry in getattr(allocation_result, 'allocated_signals', []):
            if not entry['signal'].tag.strip():
                return 'Allocated'
        for sig in getattr(allocation_result, 'unallocated_signals', []):
            if not sig.tag.strip():
                return 'Unallocated'
        return 'Unknown — signal not found in allocation data'

    if tq is not None and getattr(tq, 'tq_id', '').startswith('TQ-ALLOC-'):
        for sig in getattr(allocation_result, 'unallocated_signals', []):
            if sig.tag.strip().casefold() == tag_lower:
                return 'Unallocated'

    for entry in getattr(allocation_result, 'allocated_signals', []):
        if entry['signal'].tag.strip().casefold() == tag_lower:
            return 'Allocated'

    for sig in getattr(allocation_result, 'unallocated_signals', []):
        if sig.tag.strip().casefold() == tag_lower:
            return 'Unallocated'

    return 'Unknown — signal not found in allocation data'


def find_related_tqs(
    tq_id: str,
    affected_item: str,
    all_tqs: list,
) -> list[dict]:
    """Find other TQs that affect the same signal tag.

    Only returns TQs whose ``affected_item`` matches exactly (case-
    insensitive).  Returns a list of ``{'tq_id': ..., 'category': ...,
    'description': ...}`` dicts, excluding the TQ identified by *tq_id*.
    """
    if not affected_item:
        return []

    tag_lower = affected_item.strip().casefold()
    if tag_lower == 'unknown':
        return []

    related = []
    for tq in all_tqs:
        if tq.tq_id == tq_id:
            continue
        if tq.affected_item.strip().casefold() == tag_lower:
            related.append({
                'tq_id': tq.tq_id,
                'category': tq.category,
                'description': tq.description,
            })
    return related


# NOTE (TQ Explanations - Detailed Formatter): Produce concise, one-sentence explanations per section.
# Retains only: Meaning, Why flagged, Affected item, Impact, Recommended action, Allocation status,
# and Related TQs when reliably linked. Strips repetitive validation prefixes.
def explain_tq(
    tq,
    allocation_result,
    all_tqs: list,
) -> dict:
    """Derive a concise, single-sentence-per-section explanation for a TQ.

    Sections returned:
    - meaning: One short sentence on what the TQ category means.
    - why_flagged: One short sentence explaining why this issue was flagged.
    - affected_item: Concise identifier of the affected signal/item.
    - impact: One short sentence on why this matters.
    - recommended_action: One short sentence stating the actionable fix.
    - allocation_status: Allocation status derived from application data.
    - related_tqs: Reliably linked related TQs (same non-empty tag).
    """
    cat_info = get_category_info(tq.category)

    # 1. Meaning (one short sentence)
    meaning = cat_info['what_it_means']

    # 2. Why flagged (one short sentence, cleaned of repetitive prefixes)
    raw_reason = tq.reason or tq.description or ''
    clean_reason = re.sub(r'^Validation finding \([^)]+\):\s*', '', raw_reason).strip()
    clean_reason = re.sub(r'\s+', ' ', clean_reason)
    if not clean_reason:
        clean_reason = 'Issue detected during input validation or allocation.'
    elif not clean_reason.endswith('.'):
        clean_reason += '.'
    why_flagged = clean_reason

    # 3. Affected item
    raw_affected = (tq.affected_item or '').strip()
    if not raw_affected or raw_affected.lower() == 'unknown':
        row_match = re.search(r'Row\s+\d+', tq.description, re.IGNORECASE)
        if row_match:
            affected_item = f"{row_match.group(0)} (Tag missing)"
        else:
            affected_item = 'Unknown item'
    else:
        affected_item = f"`{raw_affected}`"

    # 4. Impact (one short sentence)
    impact = cat_info['why_it_matters']

    # 5. Recommended action (one short sentence)
    raw_action = (tq.suggested_action or cat_info['corrective_action']).strip()
    raw_action = re.sub(r'\s+', ' ', raw_action)
    if not raw_action.endswith('.'):
        raw_action += '.'
    recommended_action = raw_action

    # 6. Allocation status derived from actual application data
    tag_clean = raw_affected.casefold() if raw_affected else ''
    allocated_slot = None
    if allocation_result:
        for entry in getattr(allocation_result, 'allocated_signals', []):
            s_tag = entry['signal'].tag.strip()
            if (tag_clean and tag_clean != 'unknown' and s_tag.casefold() == tag_clean) or (
                (not tag_clean or tag_clean == 'unknown') and not s_tag
            ):
                allocated_slot = entry['charm_slot'].charm_id
                break

    alloc_status = lookup_allocation_status(raw_affected, allocation_result, tq=tq)
    is_duplicate_tq = tq.category == 'naming' or 'duplicate' in tq.description.lower()
    is_alloc_tq = getattr(tq, 'tq_id', '').startswith('TQ-ALLOC-')

    if alloc_status == 'Allocated':
        if is_duplicate_tq or is_alloc_tq:
            if allocated_slot:
                allocation_status_str = f"Unallocated (duplicate row; primary instance allocated to slot {allocated_slot})."
            else:
                allocation_status_str = "Unallocated (duplicate row)."
        elif allocated_slot:
            allocation_status_str = f"Allocated (slot {allocated_slot})."
        else:
            allocation_status_str = "Allocated."
    elif alloc_status == 'Unallocated':
        if is_duplicate_tq and allocated_slot:
            allocation_status_str = f"Unallocated (duplicate row; primary instance allocated to slot {allocated_slot})."
        else:
            allocation_status_str = "Unallocated (no hardware slot assigned)."
    else:
        allocation_status_str = alloc_status

    # 7. Related TQs (when reliably linked)
    if raw_affected and raw_affected.lower() != 'unknown':
        related_tqs = find_related_tqs(tq.tq_id, raw_affected, all_tqs)
    else:
        related_tqs = []

    return {
        'meaning': meaning,
        'why_flagged': why_flagged,
        'affected_item': affected_item,
        'impact': impact,
        'recommended_action': recommended_action,
        'allocation_status': allocation_status_str,
        'related_tqs': related_tqs,
    }

