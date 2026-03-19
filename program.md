# autoresearch

This is an experiment to have the LLM do its own research — optimizing DeepResearcher's report quality to match Gemini Deep Research.

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar19`). The branch `research/<tag>` must not already exist.
2. **Create the branch**: `git checkout -b research/<tag>` from current HEAD.
3. **Read the in-scope files**: Read these files for full context:
   - READ-ONLY CONTEXT:
     - `deep_researcher/workflow.py` (orchestration engine — understand flow but modifications here are secondary)
     - `deep_researcher/state.py` (data structures)
     - `deep_researcher/llm.py` (LLM routing)
     - `deep_researcher/search.py` (search & fetch)
     - `deep_researcher/json_utils.py` (JSON extraction)
     - `sample_result/Deep Research 技术探索与实现.md` (Gemini reference report)
     - `queries.json` (test queries)
     - `evaluate.py` (scoring script)
   - TARGET FILES (what you modify):
     - `deep_researcher/prompts.py` (all system prompts — primary target)
     - `deep_researcher/config.py` (default parameters — secondary target)
4. **Verify prerequisites**: Ensure `uv run python -m deep_researcher --help` works.
5. **Initialize results.tsv**: Create `results.tsv` with just the header row.
6. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

Each experiment runs DeepResearcher with real LLM calls against Query 1 from queries.json.

**Execute command**: `uv run python -m deep_researcher --question "研究一下Deep Research的进展和原理，重点关注几个已经生产中应用的例如Gemini Deep Research, Claude Deep Research, OpenAI Deep Research 它们的blog、代码、实现。我会用来尝试自己实现Deep Research和分享相关的技术原理。" > run.log 2>&1`

**What you CAN do:**
- Modify: `deep_researcher/prompts.py`, `deep_researcher/config.py`

**What you CANNOT do:**
- Do not modify `workflow.py`, `state.py`, `llm.py`, `search.py`, `json_utils.py`, `evaluate.py`, or any test files
- Do not install new packages
- Do not change the CLI interface or add new command-line arguments
- Do not modify the evaluate.py scoring script

**The goal**: Make DeepResearcher produce reports that match Gemini Deep Research quality in: structure, paragraph depth, reasoning quality, narrative coherence, citation density, use of tables, and executive summary richness. The metric is **composite score** — higher is better.

## Key insights for optimization

The user identified these critical gaps:
1. **Progressive search**: Search should be iterative — after finding initial results, the system should think about what's missing and search for NEW things. The gap review loop enables this, but prompts should encourage more aggressive follow-up query generation.
2. **Stronger writing**: When writing the final report with all evidence in hand, the system needs MUCH deeper analytical thinking. Longer paragraphs, mechanism-level reasoning, rich narrative flow.
3. **Structural matching**: Gemini reports have rich executive summaries (paragraph form, not bullets), 6-10 major sections with subsections, comparison tables, and numbered end-note citations with 30-45 references.

## Output format

The execute command produces a report in `runs/<run_id>/report.md`. After execution:

1. Find the latest run: `ls -td runs/202* | head -1`
2. Run evaluation: `uv run python evaluate.py <latest_run>/report.md --no-llm`
3. Extract the metric: `grep "^METRIC:" run.log` OR `uv run python evaluate.py <latest_run>/report.md --no-llm 2>/dev/null | grep "^METRIC:"`

If `run.log` doesn't contain the METRIC line, run evaluate.py manually against the latest report.

## Logging results

When an experiment is done, log it to `results.tsv` (tab-separated).

The TSV has a header row and 5 columns:

```
commit	score	status	description	notes
```

1. git commit hash (short, 7 chars)
2. composite score achieved — use 0 for crashes
3. status: `keep`, `discard`, or `crash`
4. short text description of what this experiment tried
5. any extra notes (optional)

## The experiment loop

The experiment runs on a dedicated branch (e.g. `research/mar19`).

LOOP FOREVER:

1. Look at the git state and past results in results.tsv
2. Propose and implement a change to the target file(s)
3. git commit
4. Run the experiment: `uv run python -m deep_researcher --question "研究一下Deep Research的进展和原理，重点关注几个已经生产中应用的例如Gemini Deep Research, Claude Deep Research, OpenAI Deep Research 它们的blog、代码、实现。我会用来尝试自己实现Deep Research和分享相关的技术原理。" > run.log 2>&1`
5. Find the latest run directory and evaluate: `uv run python evaluate.py $(ls -td runs/202* | head -1)/report.md --no-llm`
6. Extract the metric from evaluate output
7. If extraction fails, the run crashed. Run `tail -n 50 run.log` and attempt a fix. If you can't fix after a few attempts, give up on this idea.
8. Record the results in results.tsv (do NOT commit results.tsv)
9. If metric improved: keep the commit (advance the branch)
10. If metric is equal or worse: `git reset --hard HEAD~1` to discard

**Timeout**: No timeout — let each run finish naturally.

**Crashes**: Use judgment — fix trivial bugs and retry, skip fundamentally broken ideas.

**NEVER STOP**: Once the loop has begun, do NOT pause to ask the human. The human might be away and expects you to work indefinitely until manually stopped. If you run out of ideas, think harder — re-read files, try combinations, try radical ideas.

## Experiment ideas (starting suggestions)

1. **Baseline**: Run as-is, establish the current score
2. **Increase section writer depth**: Change "4-8 short paragraphs" to "8-15 substantive paragraphs" in section writer prompt
3. **Rich executive summary**: Change overview prompt to generate paragraph-form summaries, not just bullets
4. **Increase max_sources_per_section**: From 3 to 5-6
5. **Increase max_chars_per_source**: From 2200 to 4000+
6. **Increase max_queries_per_section**: From 2 to 3-4
7. **Add table instructions**: Tell section writer to include comparison tables where relevant
8. **Narrative flow instructions**: Tell writers to reference other sections and create throughlines
9. **Increase writer max_output_tokens**: From 8000 to 12000+
10. **Researcher prompt: more follow_up_queries**: Encourage more aggressive follow-up query generation
11. **Planner prompt: more sections**: Increase max_sections from 5 to 7-8
12. **Citation density**: Instruct writer to cite after every factual claim
