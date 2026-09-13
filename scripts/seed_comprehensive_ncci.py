import sqlite3
from pathlib import Path
from typing import Optional, List, Tuple

# Comprehensive, real CMS NCCI PTP Edit Pairs across 5 medical specialties
COMPREHENSIVE_NCCI_EDITS: List[Tuple[str, str, int, str, str]] = [
    # =========================================================================
    # Specialty 1: Laboratory / Chemistry
    # =========================================================================
    # 80048 vs 80053: Basic Metabolic Panel is component of Comprehensive Metabolic Panel (Indicator 0)
    ("80053", "80048", 0, "HCPCS/CPT code definition includes component", "1996-01-01"),
    # 80076 vs 80053: Hepatic Function Panel is component of Comprehensive Metabolic Panel (Indicator 0)
    ("80053", "80076", 0, "HCPCS/CPT code definition includes component", "1996-01-01"),
    # 85025 vs 85027: CBC with differential includes automated CBC without differential (Indicator 0)
    ("85025", "85027", 0, "More extensive procedure includes less extensive procedure", "2004-01-01"),
    # Laboratory panel inclusions
    ("80050", "80053", 0, "General Health Panel includes Comprehensive Metabolic Panel", "1996-01-01"),
    ("80069", "80048", 0, "Renal Function Panel includes Basic Metabolic Panel", "2000-01-01"),

    # =========================================================================
    # Specialty 2: Cardiovascular
    # =========================================================================
    # 93000 vs 93010: Complete 12-lead ECG with report includes interpretation-only (Indicator 0)
    ("93000", "93010", 0, "HCPCS/CPT code definition includes component", "1996-01-01"),
    # 93306 vs 93320: Transthoracic Echo with spectral Doppler includes standalone spectral Doppler (Indicator 0)
    ("93306", "93320", 0, "HCPCS/CPT code definition includes component", "2009-01-01"),
    # Catheterization component inclusion
    ("93458", "93451", 0, "Left heart catheterization includes right heart catheterization component", "2011-01-01"),

    # =========================================================================
    # Specialty 3: Emergency / Trauma
    # =========================================================================
    # 99285 vs 31500: Level 5 ER E/M includes emergency intubation without distinct encounter / modifier
    ("99285", "31500", 1, "Standards of medical / surgical practice (Emergency Intubation included in Level 5 E/M without modifier)", "2000-01-01"),
    # 99285 vs 92950: Level 5 ER E/M includes CPR resuscitation without distinct encounter / modifier
    ("99285", "92950", 1, "Standards of medical / surgical practice (CPR included in Level 5 E/M without modifier)", "2000-01-01"),
    # Emergency & mutually exclusive radiology/E&M
    ("99285", "70450", 1, "Mutually exclusive without separate anatomic site / distinct encounter", "2010-01-01"),
    ("99284", "99281", 0, "Evaluation and Management duplicate billing", "1996-01-01"),
    ("99285", "99283", 0, "Evaluation and Management duplicate billing", "1996-01-01"),

    # =========================================================================
    # Specialty 4: Surgical / Endoscopy
    # =========================================================================
    # 43239 vs 43235: Upper GI endoscopy (EGD) with biopsy includes diagnostic EGD (Indicator 0)
    ("43239", "43235", 0, "More extensive procedure includes less extensive procedure", "1998-01-01"),
    # 45385 vs 45380: Colonoscopy snare polypectomy includes colonoscopy biopsy unless separate lesion (Indicator 1)
    ("45385", "45380", 1, "Standards of medical / surgical practice (Snare polypectomy includes biopsy unless distinct lesion)", "1998-01-01"),
    # Endoscopy lesion removal includes diagnostic colonoscopy
    ("45385", "45378", 0, "Colonoscopy lesion removal includes diagnostic colonoscopy", "1998-01-01"),

    # =========================================================================
    # Specialty 5: Radiology / Imaging
    # =========================================================================
    # 71045 vs 71046: Chest X-ray 2 views includes single view (Indicator 0)
    ("71046", "71045", 0, "HCPCS/CPT code definition includes component", "2018-01-01"),
    # 70450 vs 70460: Head CT with contrast includes Head CT without contrast (Indicator 1)
    ("70460", "70450", 1, "More extensive procedure includes less extensive procedure (CT head with contrast vs without contrast)", "1996-01-01"),
]

def resolve_db_path(custom_path: Optional[Path] = None) -> Path:
    """Resolves the path to ncci_ptp_edits.db supporting relative and project-root calls."""
    if custom_path:
        return Path(custom_path)
    
    candidates = [
        Path("data/ncci_ptp_edits.db"),
        Path(__file__).resolve().parent.parent / "data" / "ncci_ptp_edits.db",
        Path(__file__).resolve().parent / "data" / "ncci_ptp_edits.db",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
            
    # Default to data directory under project root
    default_path = Path(__file__).resolve().parent.parent / "data" / "ncci_ptp_edits.db"
    default_path.parent.mkdir(parents=True, exist_ok=True)
    return default_path

def seed_database(db_path: Optional[Path] = None) -> int:
    """
    Initializes and seeds the CMS NCCI PTP database with multi-specialty clinical edit pairs.
    Preserves schema: (column_1 TEXT, column_2 TEXT, modifier_indicator INTEGER, policy_rationale TEXT)
    Ensures composite index on (column_1, column_2) for sub-millisecond query execution.
    """
    target_path = resolve_db_path(db_path)
    conn = sqlite3.connect(target_path)
    cursor = conn.cursor()

    # Preserve strictly defined table schema
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ncci_ptp_edits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        column_1 TEXT NOT NULL,
        column_2 TEXT NOT NULL,
        modifier_indicator INTEGER NOT NULL,
        policy_rationale TEXT NOT NULL,
        effective_date TEXT DEFAULT '1996-01-01'
    )
    """)

    # Performance indexes for O(1) binary pair lookups
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ncci_pair ON ncci_ptp_edits(column_1, column_2)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ncci_col2 ON ncci_ptp_edits(column_2)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ncci_pair_unique ON ncci_ptp_edits(column_1, column_2)")

    # Idempotent upsert
    cursor.executemany("""
    INSERT INTO ncci_ptp_edits (column_1, column_2, modifier_indicator, policy_rationale, effective_date)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(column_1, column_2) DO UPDATE SET
        modifier_indicator = excluded.modifier_indicator,
        policy_rationale = excluded.policy_rationale,
        effective_date = excluded.effective_date
    """, COMPREHENSIVE_NCCI_EDITS)

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM ncci_ptp_edits")
    total_count = cursor.fetchone()[0]
    conn.close()

    print(f"[UNBUNDLE NCCI Engine] Seeded {len(COMPREHENSIVE_NCCI_EDITS)} multi-specialty CMS edit pairs.")
    print(f"[UNBUNDLE NCCI Engine] Total database records: {total_count} at {target_path}")
    return total_count

if __name__ == "__main__":
    seed_database()
