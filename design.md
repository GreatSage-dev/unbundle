# UNBUNDLE // DESIGN SYSTEM & LANDING PAGE ARCHITECTURE

## 1. Visual Identity & Art Direction
* **Style:** 3D Glassmorphic Claymorphism / Translucent Refractive Acrylic
* **Color Palette:**
  * **Canvas:** Matte Obsidian (`#030712`) / Deep Slate (`#0B0F19`)
  * **Accent / Brand:** Vivid Violet (`#8B5CF6`) & Radiant Lavender (`#C084FC`)
  * **Alert / Excision:** Crimson Hazard (`#EF4444`) & Coral Alert (`#F87171`)
  * **Verification / Lawful:** Emerald Safe (`#10B981`)
* **Typography:**
  * **Headings & Body:** Inter (Modern geometric sans-serif)
  * **Data & Telemetry:** JetBrains Mono (CPT codes, dollar figures, Cedar rules, ERISA citations)

---

## 2. Section-by-Section Architecture & Illustration Mapping

### Section 1: The Autonomous Interceptor (Hero)
* **Illustration:** `shield_interceptor.png`
* **Visual Anchor:** Floating 3D hospital bill on a matte pedestal guarded by an illuminated violet shield.
* **Core Value:** Silent vigilance powered by Amazon Bedrock AgentCore. Ingests EOBs directly from payor feeds, passes clean claims with 0 interruptions (Silence Ledger), and alerts only when financial harm is detected.
* **Key Metric:** `0 Pings Sent on Clean Claims | 100% Deterministic`.

### Section 2: Surgical Code Decoupling (The Audit Engine)
* **Illustration:** `unbundling_scalpel.png`
* **Visual Anchor:** Translucent frosted hospital bill with a precision 3D scalpel cleanly excising the unbundled charge ($410).
* **Core Value:** Deterministic mathematical truth against CMS National Correct Coding Initiative (NCCI) SQLite tables. Intercepts PTP Indicator 0 collisions, Modifier 59 abuse, and CARC 97 balance shifts in under 0.3 seconds.
* **Key Metric:** `$3,620.00 Excised in 0.305 Seconds | Zero Hallucinated CPTs`.

### Section 3: The Least-Privilege Gate (AWS Cedar Security)
* **Illustration:** `cedar_lock_gate.png`
* **Visual Anchor:** Heavy refractive acrylic padlock sealed over a medical claim file with a member avatar key token hovering above.
* **Core Value:** Authority Attenuation. The AI agent is physical code-bound: `forbid dispatch_dispute unless context.human_approval_token_valid`. The agent compiles the dispute, but only the patient can turn the key.
* **Key Metric:** `Formal AWS Cedar Rust Evaluation | Zero Autonomous Runaway Risk`.

### Section 4: Post-Dispatch Reality (ERISA § 503 Statutory Clock)
* **Illustration:** `erisa_clock_dossier.png`
* **Visual Anchor:** Multi-tabbed legal dossier (Appeal, Evidence, Legal) topped with a glowing 30-day countdown timer.
* **Core Value:** Modeling what happens after dispatch. Enforces the 30-day federal statutory deadline under 29 CFR § 2560.503-1, handles the 34% payor rejection rate, and automates Level 2 State Department of Insurance (DOI) complaint filings.
* **Key Metric:** `30-Day Federal Adjudication Clock | Automatic State DOI Docketing`.

---

## 3. Asset Specifications
All images converted to lossless, optimized PNGs and staged:
* `src/ui/static/images/shield_interceptor.png` (512x512, 32-bit RGBA)
* `src/ui/static/images/unbundling_scalpel.png` (512x512, 32-bit RGBA)
* `src/ui/static/images/cedar_lock_gate.png` (512x512, 32-bit RGBA)
* `src/ui/static/images/erisa_clock_dossier.png` (512x512, 32-bit RGBA)
