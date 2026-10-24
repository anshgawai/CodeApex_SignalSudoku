"""Deterministic first-fit allocator for Signal Sudoku's hackathon MVP."""
from dataclasses import dataclass, field
from typing import Any
import math
import pandas as pd
from core.signal_classification import SignalClassifier
from core.naming_engine import NamingConfig, NamingEngine

@dataclass
class Signal:
    tag: str
    io_type: str
    cable: str = ''
    pair: str = ''
    group: str = ''
    segregation: str = ''
    charm_type: str = 'Unknown'
    terminal_block: str = 'Unknown'
    classification_confidence: str = 'definite'
    classification_notes: str = ''

@dataclass
class CharmSlot:
    charm_id: str
    baseplate_id: str = ''
    cioc_id: str = ''
    cabinet_id: str = ''
    signal: Any = None
    is_spare: bool = False

@dataclass
class Baseplate:
    baseplate_id: str
    charms: list = field(default_factory=list)
    capacity: int = 12
    is_spare: bool = False
    @property
    def used_slots(self): return sum(1 for c in self.charms if c.signal is not None)
    @property
    def available_slots(self): return self.capacity - self.used_slots
    @property
    def utilization(self): return 100 * self.used_slots / self.capacity if self.capacity else 0

@dataclass
class CIOC:
    cioc_id: str
    baseplates: list = field(default_factory=list)
    capacity: int = 96
    @property
    def used_slots(self): return sum(bp.used_slots for bp in self.baseplates)
    @property
    def total_capacity(self): return self.capacity
    @property
    def utilization(self): return 100 * self.used_slots / self.capacity if self.capacity else 0

@dataclass
class Cabinet:
    cabinet_id: str
    controller_id: str
    marshalling_id: str
    ciocs: list = field(default_factory=list)
    capacity: int = 384
    @property
    def used_slots(self): return sum(c.used_slots for c in self.ciocs)
    @property
    def total_capacity(self): return self.capacity
    @property
    def utilization(self): return 100 * self.used_slots / self.capacity if self.capacity else 0

@dataclass
class AllocationResult:
    signals: list
    allocated_signals: list = field(default_factory=list)
    unallocated_signals: list = field(default_factory=list)
    cabinets: list = field(default_factory=list)
    tq_items: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    statistics: dict = field(default_factory=dict)

class AllocationEngine:
    """Greedy allocator enforcing enabled structural constraints where feasible."""
    def __init__(self, rules: dict):
        self.rules = dict(rules)
        n = self.rules.get('naming', {})
        self.naming = NamingEngine(NamingConfig(
            area=n.get('area','AR1'), unit=n.get('unit','100'),
            cabinet_pattern=n.get('cabinet_pattern','{area}-DCS-{unit}-{seq:02d}'),
            controller_pattern=n.get('controller_pattern','{area}CTL{unit}{seq:02d}'),
            marshalling_pattern=n.get('marshalling_pattern','{area}-DCM-{unit}-{seq:02d}'),
            cioc_pattern=n.get('cioc_pattern','{area}CIOC{unit}{seq:03d}'),
            baseplate_pattern=n.get('baseplate_pattern','{cioc_seq:03d}-CBP-{seq}'),
            cabinet_start_seq=n.get('cabinet_start_seq',1), cioc_start_seq=n.get('cioc_start_seq',1),
            baseplate_start_seq=n.get('baseplate_start_seq',1)))
        self.classifier = SignalClassifier(default_do_subtype=self.rules.get('default_do_subtype','normal'))
        self._cab_seq = n.get('cabinet_start_seq',1); self._cioc_seq=n.get('cioc_start_seq',1)
        self._cabinet_by_key = {}; self._cioc_by_key = {}; self._bp_by_key = {}
        self._seg_by_cioc = {}; self._cable_bp = {}; self._group_cab = {}
        self._next_charm = {}
        self._bp_capacity = int(self.rules.get('charms_per_baseplate',12))
        self._bp_per_cioc = int(self.rules.get('baseplates_per_cioc',8))
        self._cioc_per_cab = int(self.rules.get('ciocs_per_cabinet',4))
        self._max_bp = self._bp_per_cioc
        if self.rules.get('reserve_spare_capacity', False):
            pct = float(self.rules.get('spare_percentage',0))
            self._max_bp = max(1, math.floor(self._bp_per_cioc * (1-pct/100)))
            if self.rules.get('spare_baseplates_per_cioc',0):
                self._max_bp = min(self._max_bp, self._bp_per_cioc-int(self.rules['spare_baseplates_per_cioc']))

    def _new_cabinet(self):
        seq=self._cab_seq; self._cab_seq += 1
        c=Cabinet(self.naming.generate_cabinet_name(seq), self.naming.generate_controller_name(seq), self.naming.generate_marshalling_name(seq), capacity=self._cioc_per_cab*self._bp_per_cioc*self._bp_capacity)
        self._cabinet_by_key[seq]=c
        self._all_cabinets.append(c)
        return c
    def _new_cioc(self, cab):
        seq=self._cioc_seq; self._cioc_seq += 1
        c=CIOC(self.naming.generate_cioc_name(seq), capacity=self._max_bp*self._bp_capacity)
        cab.ciocs.append(c); self._cioc_by_key[c.cioc_id]=c; self._seg_by_cioc[c.cioc_id]=set()
        return c
    def _new_bp(self, cioc):
        seq=len(cioc.baseplates)+1
        bp=Baseplate(self.naming.generate_baseplate_name(self._cioc_seq-1,seq), capacity=self._bp_capacity)
        for i in range(1,self._bp_capacity+1): bp.charms.append(CharmSlot(f'{bp.baseplate_id}-CH-{i:02d}', bp.baseplate_id, cioc.cioc_id, next((c.cabinet_id for c in self._all_cabinets if cioc in c.ciocs), '')))
        cioc.baseplates.append(bp); self._bp_by_key[bp.baseplate_id]=bp
        return bp
    def _ciocs(self): return [(cab,cioc) for cab in self._all_cabinets for cioc in cab.ciocs]
    def _all_slots(self):
        for cab in self._all_cabinets:
            for cioc in cab.ciocs:
                for bp in cioc.baseplates:
                    for slot in bp.charms: yield cab,cioc,bp,slot
    def _make_signal(self,row):
        def val(k):
            x=row.get(k,''); return '' if pd.isna(x) else str(x).strip()
        io=val('IO').upper(); cls=self.classifier.classify(io)
        return Signal(val('Tag'),io,val('Cable'),val('Pair'),val('Grp'),val('Seg'),cls.charm_type,cls.terminal_block,cls.confidence,cls.notes)

    def allocate(self, df: pd.DataFrame, preferred_slots: dict = None) -> AllocationResult:
        """Allocate signals to hardware slots.

        Args:
            df: Normalised I/O MDB DataFrame.
            preferred_slots: Optional map of tag -> previous charm_id. When
                provided, the engine tries to keep those assignments if they
                remain valid under the active rules (minimises reassignment).
        """
        preferred_slots = preferred_slots or {}
        ndf=df.copy(); ndf.columns=[str(c).strip() for c in ndf.columns]
        for col in ['Tag','IO','Cable','Pair','Grp','Seg']:
            if col not in ndf: ndf[col]=''
        signals = [self._make_signal(row) for _, row in ndf.iterrows()]
        result = AllocationResult(signals=signals)
        self._all_cabinets = result.cabinets

        # Prevent duplicate tags from being allocated to multiple CHARM slots.
        seen_tags = set()
        unique_signals = []

        for sig in signals:
            tag_key = sig.tag.strip().casefold()

            if tag_key and tag_key in seen_tags:
                result.unallocated_signals.append(sig)
                result.tq_items.append({
                    'affected_item': sig.tag,
                    'category': 'naming',
                    'reason': f"Duplicate tag '{sig.tag}'",
                    'description': 'Rename or remove the duplicate tag before allocation.'
                })
                continue

            if tag_key:
                seen_tags.add(tag_key)

            unique_signals.append(sig)

        # NOTE (Allocation Count Fix): Preserve all raw input rows in `result.signals`
        # and use `signals_to_allocate` for unique signals during placement. Duplicate tag
        # rows are placed into `result.unallocated_signals`, ensuring every input row is accounted for.
        signals_to_allocate = unique_signals
        # Group / cable / pair ordering controlled by configurable preferences.
        def pair_key(s):
            try: return (0,int(s.pair))
            except (ValueError,TypeError): return (1,s.pair)
        use_pair = self.rules.get('maintain_pair_order', True)
        signals_to_allocate.sort(key=lambda s:(
            s.group if self.rules.get('keep_groups_together',True) else '',
            s.cable if self.rules.get('keep_cables_together',True) else '',
            pair_key(s) if use_pair else (0, ''),
            s.tag,
        ))

        # Seed hardware tree from preferred slots so preservation can succeed.
        # Reserve preferred charm IDs for their owners so other signals cannot steal them.
        reserved_charms = set(preferred_slots.values()) if preferred_slots else set()
        if preferred_slots:
            self._seed_from_preferred(preferred_slots)

        def _place(sig):
            if sig.charm_type == 'Unknown' or sig.terminal_block == 'Unknown':
                result.unallocated_signals.append(sig)
                result.tq_items.append({
                    'affected_item': sig.tag,
                    'category': 'mapping',
                    'reason': f'Unknown I/O type: {sig.io_type}',
                    'description': 'Signal type needs engineering classification',
                })
                return
            place = None
            pref_id = preferred_slots.get(sig.tag)
            if pref_id:
                place = self._try_preferred_slot(sig, pref_id)
            if place is None:
                place = self._find_slot(sig, reserved_charms=reserved_charms, own_pref=pref_id)
            if place is None:
                result.unallocated_signals.append(sig)
                result.tq_items.append({
                    'affected_item': sig.tag,
                    'category': 'capacity',
                    'reason': 'No available slot satisfies the active constraints',
                    'description': 'No feasible hardware slot found',
                })
                return
            cab, cioc, bp, slot = place
            slot.signal = sig
            result.allocated_signals.append({'signal': sig, 'charm_slot': slot})
            # Owner has claimed their preferred slot — release reservation.
            reserved_charms.discard(slot.charm_id)
            seg = sig.segregation.upper()
            if seg:
                self._seg_by_cioc[cioc.cioc_id].add(seg)
            if sig.cable:
                self._cable_bp.setdefault(sig.cable, set()).add(bp.baseplate_id)
            if sig.group:
                self._group_cab.setdefault(sig.group, set()).add(cab.cabinet_id)

        # Place preferred-slot owners first to maximise preservation, then the rest.
        with_pref = [s for s in signals_to_allocate if s.tag in preferred_slots]
        without_pref = [s for s in signals_to_allocate if s.tag not in preferred_slots]
        for sig in with_pref:
            _place(sig)
        for sig in without_pref:
            _place(sig)

        # NOTE (Allocation Count Fix): Reconcile metrics across all input rows.
        # `total_signals` is the total input count (len(result.signals)), ensuring that:
        # allocated_signals + unallocated_signals == total_signals == len(input_df).
        # `unique_signals` tracks the count of distinct non-duplicate tags.
        result.statistics = {
            'total_signals': len(result.signals),
            'allocated': len(result.allocated_signals),
            'unallocated': len(result.unallocated_signals),
            'cabinets': len(result.cabinets),
            'ciocs': sum(len(c.ciocs) for c in result.cabinets),
            'baseplates': sum(len(ci.baseplates) for c in result.cabinets for ci in c.ciocs),
            'unique_signals': len(unique_signals),
        }
        return result

    def _seed_from_preferred(self, preferred_slots: dict) -> None:
        """Ensure cabinets/CIOCs/baseplates exist for previously used charm IDs."""
        needed = set(preferred_slots.values())
        if not self._all_cabinets:
            self._new_cabinet()
            self._new_cioc(self._all_cabinets[0])
            self._new_bp(self._all_cabinets[0].ciocs[0])
        for _ in range(len(needed) + 64):
            existing = {slot.charm_id for _, _, _, slot in self._all_slots()}
            missing = needed - existing
            if not missing:
                return
            cab = self._all_cabinets[-1]
            expanded = False
            for cioc in cab.ciocs:
                if len(cioc.baseplates) < self._max_bp:
                    self._new_bp(cioc)
                    expanded = True
                    break
            if expanded:
                continue
            if len(cab.ciocs) < self._cioc_per_cab:
                cioc = self._new_cioc(cab)
                self._new_bp(cioc)
                continue
            cab = self._new_cabinet()
            cioc = self._new_cioc(cab)
            self._new_bp(cioc)

    def _try_preferred_slot(self, sig, charm_id: str):
        """Return preferred placement if free and valid under active rules."""
        seg = sig.segregation.upper()
        for cab, cioc, bp, slot in self._all_slots():
            if slot.charm_id != charm_id:
                continue
            if slot.signal is not None:
                return None
            if not self._slot_allowed(sig, cab, cioc, bp, seg):
                return None
            return cab, cioc, bp, slot
        return None

    def _slot_allowed(self, sig, cab, cioc, bp, seg: str) -> bool:
        """Return True if placing *sig* on this slot obeys active rules."""
        if self.rules.get('enforce_segregation', True) and seg and self._seg_by_cioc.get(cioc.cioc_id) and seg not in self._seg_by_cioc[cioc.cioc_id]:
            return False
        if self.rules.get('keep_groups_together', True) and sig.group and self._group_cab.get(sig.group) and cab.cabinet_id not in self._group_cab[sig.group]:
            return False
        if self.rules.get('keep_cables_together', True) and sig.cable and self._cable_bp.get(sig.cable) and bp.baseplate_id not in self._cable_bp[sig.cable]:
            if any(x[2].baseplate_id in self._cable_bp[sig.cable] and x[2].available_slots > 0 for x in self._all_slots()):
                return False
        return True

    def _find_slot(self, sig, reserved_charms=None, own_pref=None):
        reserved_charms = reserved_charms or set()
        seg = sig.segregation.upper()
        candidates = list(self._all_slots())
        candidates.sort(key=lambda x: (
            0 if sig.cable and x[2].baseplate_id in self._cable_bp.get(sig.cable, set()) else 1,
            0 if sig.group and x[0].cabinet_id in self._group_cab.get(sig.group, set()) else 1,
        ))
        for cab, cioc, bp, slot in candidates:
            if slot.signal is not None:
                continue
            if slot.charm_id in reserved_charms and slot.charm_id != own_pref:
                continue
            if not self._slot_allowed(sig, cab, cioc, bp, seg):
                continue
            return cab, cioc, bp, slot
        # Prefer expanding the existing cabinet/group before creating new hardware.
        preferred_cabs = []
        if self.rules.get('keep_groups_together', True) and sig.group and self._group_cab.get(sig.group):
            preferred_cabs = [c for c in self._all_cabinets if c.cabinet_id in self._group_cab[sig.group]]
        else:
            preferred_cabs = list(self._all_cabinets)
        for cab in preferred_cabs:
            for cioc in cab.ciocs:
                if len(cioc.baseplates) < self._max_bp:
                    if not (self.rules.get('enforce_segregation', True) and seg and self._seg_by_cioc.get(cioc.cioc_id) and seg not in self._seg_by_cioc[cioc.cioc_id]):
                        bp = self._new_bp(cioc)
                        return cab, cioc, bp, bp.charms[0]
            if len(cab.ciocs) < self._cioc_per_cab:
                cioc = self._new_cioc(cab)
                bp = self._new_bp(cioc)
                return cab, cioc, bp, bp.charms[0]
        # If a group already has a home cabinet, do not silently violate the rule by moving it elsewhere.
        if self.rules.get('keep_groups_together', True) and sig.group and self._group_cab.get(sig.group):
            return None
        cab = self._new_cabinet()
        cioc = self._new_cioc(cab)
        bp = self._new_bp(cioc)
        return cab, cioc, bp, bp.charms[0]
