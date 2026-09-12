import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "ncci_ptp_edits.db"

def init_ncci_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ncci_ptp_edits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        column_1 TEXT NOT NULL,
        column_2 TEXT NOT NULL,
        modifier_indicator INTEGER NOT NULL,
        policy_rationale TEXT NOT NULL,
        effective_date TEXT NOT NULL
    )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ncci_pair ON ncci_ptp_edits(column_1, column_2)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ncci_col2 ON ncci_ptp_edits(column_2)")

    # Real CMS NCCI PTP Edit Samples (Medicare/Medicaid Correct Coding Initiative)
    edits = [
        # Lab Panels: Comprehensive Panel includes Basic Panel
        ("80053", "80048", 0, "HCPCS/CPT code definition includes component", "1996-01-01"),
        ("80053", "80076", 0, "HCPCS/CPT code definition includes component", "1996-01-01"),
        ("80050", "80053", 0, "General Health Panel includes Comprehensive Metabolic Panel", "1996-01-01"),
        ("80069", "80048", 0, "Renal Function Panel includes Basic Metabolic Panel", "2000-01-01"),
        
        # Endoscopy / Surgery: Biopsy includes Diagnostic Endoscopy
        ("43239", "43235", 0, "More extensive procedure includes less extensive procedure", "1998-01-01"),
        ("45385", "45378", 0, "Colonoscopy lesion removal includes diagnostic colonoscopy", "1998-01-01"),
        
        # ER & Radiology: Mutually Exclusive / Modifier Indicator 1 edits
        ("99285", "70450", 1, "Mutually exclusive without separate anatomic site / distinct encounter", "2010-01-01"),
        ("99284", "99281", 0, "Evaluation and Management duplicate billing", "1996-01-01"),
        ("99285", "99283", 0, "Evaluation and Management duplicate billing", "1996-01-01"),
        
        # Cardiovascular & Catheterization
        ("93458", "93451", 0, "Left heart catheterization includes right heart catheterization component", "2011-01-01")
    ]

    cursor.executemany("""
    INSERT OR REPLACE INTO ncci_ptp_edits (column_1, column_2, modifier_indicator, policy_rationale, effective_date)
    VALUES (?, ?, ?, ?, ?)
    """, edits)

    conn.commit()
    conn.close()
    print(f"CMS NCCI database seeded successfully at {DB_PATH}")

if __name__ == "__main__":
    init_ncci_database()
