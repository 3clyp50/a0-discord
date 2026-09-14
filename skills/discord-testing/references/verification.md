# Verify a fix

## Establish the target

Identify the requested repository, revision, reproduction and expected result. Read its local instructions and the changed code with relevant callers. Keep requested source, inspected checkout and running application distinct; record which revision a test actually exercises.

A commit being available does not mean it is deployed. An older project checkout does not by itself disprove a fix in a different target. Use an isolated snapshot when necessary and authorized; never switch, pull into, or overwrite the operator's working tree to make the evidence agree. If the requested build cannot be executed, test the available build and label the difference, or report the exact blocker.

## Execute, do not only summarize

Start with the smallest existing regression check that covers the reported failure. Agent Zero has separate environments: /opt/venv/bin/python runs agent code and ordinary test tooling; /opt/venv-a0/bin/python runs the framework. Confirm these paths in the deployment and use the interpreter explicitly, never bare pip or guessed PATH activation.

If pytest is missing and its installation is authorized, run /opt/venv/bin/python -m pip install pytest, then /opt/venv/bin/python -m pytest for suitable tests. Honor standing approval without asking again. Do not install it into /opt/venv-a0, use system pip, or expose one environment's site-packages to the other. Permission for pytest does not grant permission to install arbitrary dependencies.

Framework/backend integration checks must use the framework runtime and its dependencies. If a suite cannot run in the agent environment, do not call that a product failure or assume installing pytest there fixed framework imports. Run supported framework unittest/standalone checks or a behavioral probe through the real application; request approval only if changes to the framework environment are necessary. Keep any unrun suite explicitly marked not run, and never rewrite an entire suite merely to avoid its runner.

Exercise the reported failure and a normal operation afterward, with explicit expected results. Use temporary files, test-owned contexts and fixtures without credentials. Bound operations and cleanup. Preserve unrelated state. Stop and report genuine access or safety blockers instead of repeatedly inspecting the same diff.

## Browser fixes

Load browser-automation first. The bundled browser uses Patchright with a Playwright-style API. Confirm whether the selected chat/project uses Internal Docker Browser or a host connector; do not guess a mode argument or silently change global Browser settings. Prefer the Internal Docker Browser for container-path checks when that is the authorized target.

Use the browser tool against a disposable local fixture and test-owned tab to exercise the real Agent Zero route. Inspect current DOM refs, perform the relevant interaction, and assert the observed result. A separate bare Playwright script can be a component check, but does not prove that Agent Zero's tool dispatch or browser backend works.

For an evaluate cancellation/deadline fix, cover normal evaluation, interruption, the reported recovery behavior, and a successful follow-up action. Check whether DOM/tab state should be preserved or reset according to the implementation contract. Check that unrelated test-owned tabs still work. Do not infer JavaScript stopped merely because the caller stopped waiting.

Never run infinite loops or unresolved promises in a shared live browser to test its safeguards. Such negative cases require an isolated browser process using the actual implementation, its own temporary profile and an outer process deadline that covers startup, evaluation and recovery. The outer watchdog must not depend on the timeout being tested. If that isolation is unavailable, run safe bounded checks and explicitly leave cancellation recovery unverified.

Docker tests do not prove host-connector behavior. Test that path only with an available authorized host and the matching connector build; otherwise list it as untested. Never turn either one-path pass into an end-to-end claim.

Use screenshots when visual state matters, load them through vision_load before interpreting them, and attach test-owned evidence through discord_send when useful. Do not publish screenshots of unrelated pages or credentials. Close only test-owned tabs, processes and fixtures; never reset a shared browser or clear its profile for cleanup.

## Report the result

Normally use 40-100 words: verdict, what ran against which target, observed outcome and the remaining gap. Prefer one source link over commit dates, author details or an inventory of changed functions. Send at most one useful progress note if testing takes time.

Distinguish inspected, compiled, suite tested, component tested and live verified. A test claimed in a commit message remains reported evidence until independently run. Record command or tool action, environment/revision, expected versus actual result and cleanup in a Markdown attachment when the detail is useful. Do not repeat the attachment inline or create catalog entries/PRs unless that is within the requested task.
