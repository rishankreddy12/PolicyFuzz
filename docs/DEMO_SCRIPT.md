# PolicyFuzz Demo Script

**Estimated time:** 5 minutes

## Preparation
1. Ensure the demo is reset: `make clean fixtures`
2. Start the application: `streamlit run policyfuzz/ui/app.py`
3. Have your terminal and browser windows open side-by-side or easily switchable.

## 0:00 - The Problem (Framing)
*Context for the audience: Large organisations suffer from massive policy divergence. Frontline agents interpret policies inconsistently, leading to customer churn, regulatory fines, or business risk.*

**Speaker notes:** "As reported in our source research (not independently verified by our own evaluations yet), one 2026 evaluation showed vendors' support agents ranged from 56% to 92% in policy compliance. Our goal is to 'fuzz test' business policies to find ambiguities *before* humans or AI agents make the wrong decision."

## 0:45 - Loading the Policy
1. In the Streamlit UI sidebar, click **"Load Demo Policy"**.
2. Explain the inputs briefly: "We're loading a standard returns policy. PolicyFuzz is now parsing this policy, generating adversarial edge-cases, and spinning up an LLM panel of three different personas: a Literalist, a Customer Advocate, and a Risk Controller."
3. Click **"Start Run"**.

## 1:15 - Verdict Matrix (Identifying Ambiguity)
1. Navigate to the **"Verdict matrix"** tab.
2. The grid will show 30 generated cases against 3 personas. 
3. **Speaker notes:** "Out of the 30 generated edge cases, we found 7 'red' rows. These are divergent cases where our 3 personas completely disagreed on what the policy allows. This proves our policy is ambiguous."

## 2:00 - Loopholes & Rulings
1. Navigate to the **"Loopholes"** tab.
2. **Speaker notes:** "PolicyFuzz automatically clusters these 7 divergent cases into 3 distinct loopholes or missing rules."
3. Make the following manual rulings (as the human policy owner):
   - **Cluster K1** -> `ALLOW`
   - **Cluster K2** -> `ALLOW`
   - **Cluster K3** -> `ESCALATE`
4. Click **"Submit Rulings"**.

## 3:00 - Patch Generation
1. Navigate to the **"Patch"** tab.
2. **Speaker notes:** "Based on our rulings, an LLM Patcher agent has rewritten specific clauses of our policy to close the loopholes. We can see exactly what text is added or replaced."
3. Check the checkboxes for all 3 proposed edits.
4. Click **"Approve Selected Edits"**.

## 3:45 - Verification & Results
1. Navigate to the **"Verification"** tab.
2. **Speaker notes:** "PolicyFuzz automatically re-runs the LLM panel against the *new* policy text. The number of divergent cases has dropped from 7 to 1! We also check 'sibling cases' to ensure our patch didn't accidentally break existing clear rules (0 regressions). Our conformance is at 90%, achieving the target threshold!"

## 4:30 - Inspecting the System
1. Briefly show the **"Log"** tab and the **"LLM Trace"** expanders.
2. **Speaker notes:** "The entire run is highly transparent. We can see every single LLM prompt, response, latency, and system event."
3. Navigate to the **"Export"** tab to show the downloadable PDF/Markdown reports.

## 5:00 - Limitations & Wrap-up
**Speaker notes:** "This demo was run in 'scripted' mode for speed and determinism. The novelty of PolicyFuzz is the *application* of these techniques to business logic and compliance, not the invention of LLMs. You can run this against local Ollama models by switching the provider in the sidebar."
