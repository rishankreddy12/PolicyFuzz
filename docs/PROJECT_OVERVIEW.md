# PolicyFuzz: SOP Divergence Auditor

## 1. What is PolicyFuzz About?

PolicyFuzz is an automated auditing tool designed to "fuzz test" written business policies, Standard Operating Procedures (SOPs), and compliance rules to uncover hidden ambiguities. 

Just as software engineers use fuzzing to throw edge-case inputs at software to find crashes, PolicyFuzz throws edge-case scenarios at a written document to find **interpretation crashes** (ambiguity). 

### How it works:
1. **Ingest & Parse**: It takes a plain-text, numbered policy (e.g., a Retail Returns Policy) and deterministically splits it into numbered clauses.
2. **Adversarial Fuzzing**: A Case Generator LLM creates ~30 boundary-hugging edge cases specifically designed to stress-test the rules (e.g., "The customer returns a scratched item on day 30 at 11:59 PM").
3. **The LLM Panel**: It spins up an independent panel of three distinct LLM personas (e.g., *Literalist*, *Customer Advocate*, *Risk Controller*). Each persona independently interprets every case against the policy.
4. **Divergence Detection**: The system deterministically finds cases where the personas completely disagree on the outcome. These "divergent cases" prove that the policy is ambiguous.
5. **Human Adjudication**: A human reviewer groups these divergent cases into "loopholes" and provides a definitive ruling (`ALLOW`, `DENY`, or `ESCALATE`).
6. **Self-Healing & Verification**: A Patcher LLM drafts exact clause rewrites to close the loopholes. PolicyFuzz then re-runs the entire panel against the *new* policy and checks sibling cases to prove mathematically that ambiguity has dropped without causing regressions.

---

## 2. Where is it Useful? (Use Cases)

In large organizations, frontline agents frequently misinterpret vague rules, leading to frustrated customers, financial leakage, or compliance breaches. PolicyFuzz is highly valuable in the following domains:

* **Customer Support & Operations:** 
  Before rolling out a new refund, shipping, or cancellation policy, operations teams can fuzz-test it to ensure all 500 support agents will interpret it identically.
* **AI Agent Safety (Pre-deployment):**
  If a company is replacing human agents with autonomous AI support bots, the bot's behavior is dictated by its system prompt (the policy). PolicyFuzz ensures the rules are perfectly watertight *before* an AI is trusted to enforce them.
* **Legal, Risk, and Compliance:**
  Compliance officers can test regulatory guidelines (e.g., expense policies, acceptable use policies) to ensure employees cannot exploit loopholes or plead ignorance due to contradictory phrasing.
* **Contract Fuzzing:**
  Testing Service Level Agreements (SLAs) or Terms of Service (ToS) to find edge cases where obligations are not clearly defined.

---

## 3. Project Scope

PolicyFuzz is designed to be a highly focused, localized, and deterministic tool. It strictly separates LLM reasoning from deterministic application logic.

### In Scope (Core Goals)
* **Textual Fuzzing:** Ingestion of plain-text policies with numeric clause structures (≤ 20 KB).
* **Controlled Generation:** Generation of exactly 24–36 adversarial test cases per run.
* **Deterministic Metrics:** Computing divergence, applying string-based clause patches, and verifying regressions purely in Python (no LLM hallucinations in the metrics).
* **Human-in-the-Loop:** A Streamlit UI that enforces strict "gates." An LLM can suggest an edit, but it cannot alter the policy without explicit human approval.
* **Traceability:** Every LLM prompt, response, latency, and human decision is logged into a local SQLite database (`events` and `llm_calls` tables) for perfect auditability.
* **Offline Demo:** A `scripted` provider mode that replays deterministic fixtures to demonstrate the workflow in 5 minutes without needing an internet connection or an active LLM.

### Out of Scope (Non-Goals)
* **Complex File Parsing:** PDF, DOCX, or OCR ingestion is unsupported.
* **RAG / Embeddings:** Multi-document cross-checking or Vector databases (Chroma, FAISS) are not used. The focus is on single-document logical cohesion.
* **Multi-User / Cloud Deployment:** There is no authentication or async job queuing (e.g., Celery). It is intended to be run locally via `streamlit run`.
* **Automated Patching:** The tool will *never* overwrite a policy without human intervention. 

---

## 4. Key Innovation

The primary novelty of PolicyFuzz is not the invention of a new LLM architecture, but rather the **application of divergence metrics to business logic**. 

Instead of relying on a single LLM to say "this policy looks good," it uses the *disagreement between isolated personas* as a mathematical signal for ambiguity, pairs it with human adjudication, and creates a closed-loop regression test.
