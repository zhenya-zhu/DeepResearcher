---
name: gemini-deep-research
description: Automate Gemini Deep Research via Chrome DevTools MCP. Use when the user wants to run a Gemini Deep Research query, asks to "deep research" a topic, or mentions "gemini research". Requires Chrome running with --remote-debugging-port=9222 and Chrome DevTools MCP configured with --browserUrl http://127.0.0.1:9222.
argument-hint: <research-topic> [--drive] [--model pro|quick|think]
allowed-tools: [Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion]
---

# Gemini Deep Research Skill

Automates the full Gemini Deep Research workflow via Chrome DevTools MCP:
1. Navigate to Gemini (second Google account)
2. Select Deep Research tool
3. Configure model (Pro/Quick/Think)
4. Configure sources (Google Search + optionally Google Drive)
5. Submit research query
6. Wait for research plan, then start research
7. Poll until report is generated
8. Extract the report text

## Prerequisites

Chrome must be running with remote debugging enabled. If not, guide the user:

```bash
# Kill existing Chrome first
killall "Google Chrome"
sleep 2

# Chrome 144+ requires a non-default user-data-dir for remote debugging.
# Create a profile directory with a symlink to the real Default profile
# so the user's login sessions and cookies are preserved:
mkdir -p "$HOME/.chrome-debug-profile"
ln -sf "$HOME/Library/Application Support/Google/Chrome/Default" "$HOME/.chrome-debug-profile/Default"

# Launch with debugging
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --remote-allow-origins="*" \
  --user-data-dir="$HOME/.chrome-debug-profile"
```

**Important**: You MUST kill all existing Chrome processes first. If Chrome is already running, a new process with `--remote-debugging-port` will hand off to the existing instance and the debugging port will never bind.

Verify connection:
```bash
curl -s http://127.0.0.1:9222/json/version
```

The Chrome DevTools MCP must be configured with `--browserUrl http://127.0.0.1:9222` in its `.mcp.json`.

## Arguments

The user invoked this with: $ARGUMENTS

Parse arguments:
- First positional argument (or everything before flags): the **research topic**
- `--drive` flag: also select Google Drive (云端硬盘) as a source. **Default: OFF** (only Google Search)
- `--model <value>`: model to use. Options: `pro`, `quick` (快速), `think` (思考). **Default: pro**

If no research topic is provided, ask the user what they want to research.

## Step-by-Step Workflow

### Step 1: Verify Chrome Connection

Use `curl -s http://127.0.0.1:9222/json/version` via Bash to confirm Chrome is reachable.
If it fails, guide the user through the Prerequisites section above.

Then call `list_pages` to confirm Chrome DevTools MCP is working.

### Step 2: Navigate to Gemini

Open a new page or navigate to: `https://gemini.google.com/u/1/app?pageId=none`

The `/u/1/` path selects the second Google account. Wait for the page to load.
Take a snapshot to confirm the page loaded and the user is logged in.

### Step 3: Select Deep Research Tool

1. Take a snapshot to find the current UI elements
2. Click the **"工具" (Tools)** button to open the tools menu
3. In the menu, click **"Deep Research"** (`menuitemcheckbox`)
4. Verify the button "取消选择"Deep Research"" appears, confirming selection

**Important**: The "来源" (Sources) button only appears AFTER Deep Research is selected. You must complete this step before configuring sources.

### Step 4: Configure Sources

After selecting Deep Research, a **"来源" (Sources)** button appears at the bottom.

1. Click the **"来源" (Sources)** button to open the sources menu
2. **Google 搜索 (Search)** should already be checked by default
3. If `--drive` flag was provided:
   - Click **"云端硬盘" (Google Drive)** to check it
4. Press Escape or click elsewhere to close the menu
5. Verify the button text shows the selected sources (e.g., "来源，已选择 Google 搜索 和 云端硬盘")

### Step 5: Select Model

1. Click the **"打开模式选择器" (Open mode selector)** button
2. In the menu, select the appropriate model:
   - `pro` → Click the menuitem containing "Pro"
   - `quick` → Click the menuitem containing "快速"
   - `think` → Click the menuitem containing "思考"

### Step 6: Submit Research Query

1. Click the text input box ("为 Gemini 输入提示")
2. Type the research topic
3. Press Enter to submit

### Step 7: Wait for Research Plan

Wait for the text "开始研究" (Start Research) to appear on the page (timeout: 60s).
This indicates Gemini has generated its research plan.

Take a snapshot to show the user the research plan.

### Step 8: Start Research

Click the **"开始研究" (Start Research)** button.

Inform the user:
> Deep Research has started. This typically takes 3-15 minutes. I'll poll every 60 seconds until the report is ready.

### Step 9: Poll for Report Completion

**Preferred method**: Use `evaluate_script` to check completion status, as `wait_for` may timeout for long-running research:

```javascript
() => {
  const statusElements = document.querySelectorAll('[role="status"]');
  const statusTexts = Array.from(statusElements).map(e => e.innerText).filter(t => t.length > 0);
  const buttons = document.querySelectorAll('button');
  const hasExport = Array.from(buttons).some(b => b.innerText.includes('导出到 Google 文档'));
  const hasCopyAll = Array.from(buttons).some(b => b.innerText.includes('复制全部'));
  return { statusTexts, hasExport, hasCopyAll, done: hasExport || hasCopyAll };
}
```

**Fallback method**: Use `wait_for` with text "导出到 Google 文档" (Export to Google Docs) and a long timeout (600000ms / 10 minutes). Note: Deep Research can take 5-20+ minutes, so a single `wait_for` may not be sufficient.

Polling strategy:
1. First, try `wait_for` with 600000ms timeout
2. If it times out, use `evaluate_script` to check `[role="status"]` elements for progress text (e.g., "已完成")
3. If not complete, take a snapshot to show the user progress, then retry

The report is complete when you see any of:
- "导出到 Google 文档" (Export to Google Docs) button
- "复制全部" (Copy All) button
- Status element shows "已完成" (Completed)
- The research status panel disappears and a full report is shown

### Step 10: Extract Report

Once the report is complete:

1. Take a snapshot to capture the full report content
2. The report text will be in the page snapshot under the Gemini response area
3. If the report is long, use `evaluate_script` to extract the full text:

```javascript
() => {
  const elements = document.querySelectorAll('.markdown');
  const last = elements[elements.length - 1];
  return last ? last.innerText : 'Report not found';
}
```

Note: Use `.markdown` selector directly (not `[data-message-id] .markdown`) as it reliably captures the report content.

4. Present the report to the user
5. Optionally save to a file if the user requests it

## Error Handling

- **Chrome not running**: Guide user to start Chrome with debugging
- **Port 9222 not binding**: Existing Chrome is running — must `killall "Google Chrome"` first
- **"non-default data directory" error (Chrome 144+)**: Create `~/.chrome-debug-profile` with symlink to real Default profile (see Prerequisites)
- **Not logged in**: If "Sign in" appears, inform user they need to log in manually
- **Deep Research not available**: May require Google AI Pro/Ultra subscription
- **Timeout waiting for report**: Use `evaluate_script` polling instead of `wait_for`; take screenshot, show progress, offer to continue waiting
- **Page navigation issues**: Timeout on navigation is normal for heavy pages; proceed with snapshot
- **"修改研究方案" button**: Do NOT click this — it sends the text as a chat message rather than opening an edit UI. Start a new conversation instead.

## Notes

- The Gemini URL uses `/u/1/` for the second Google account. Adjust the number for different accounts.
- Deep Research reports can take 3-20+ minutes depending on topic complexity.
- The skill uses Chinese UI labels because the Gemini interface language matches the user's Google account settings.
- The correct workflow order is: Deep Research tool → Sources → Model → Submit query. Sources button only appears after selecting Deep Research.
- When starting a new research after a failed/cancelled one, navigate to a fresh conversation URL (`?pageId=none`) rather than trying to edit an existing research plan.
