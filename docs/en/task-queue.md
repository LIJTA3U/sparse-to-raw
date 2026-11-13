# Advanced task queue (v0.6.0)

The task queue processes Sparse images and QFIL XML packages sequentially. It deliberately runs one job at a time to avoid competing disk-heavy operations.

## Preparing the queue

- Add one or more input images. Duplicate paths are ignored.
- Use **Add QFIL task** to select one or more `rawprogram*.xml` manifests, optional `patch*.xml` manifests, a firmware/search folder, and a dedicated output folder. The selected paths and options are stored with that queue item for the current queue session.
- Reorder waiting tasks by dragging rows or using **Move up / Move down**. The order shown is the processing order.
- Choose the output directory and overwrite policy.
- Choose whether to verify each written RAW file.
- Use **Save profile** to store task definitions/order and the output, overwrite, and verification options in JSON. **Load profile** replaces the current queue after confirmation.
- Profiles support Sparse → RAW, RAW → Sparse, and QFIL tasks. Runtime statuses (success/failed/cancelled) are not persisted; all restored tasks start in the waiting state.
- Paths are stored relative to the profile file when possible. A profile can move together with its related file tree; paths on a different Windows drive may remain absolute. The application warns about missing input files after loading.
- Select a status filter to focus on waiting, running, successful, failed, cancelled, or skipped items.

## Controls while the queue is running

- **Pause** requests a pause at the next task boundary. The current file is allowed to finish; it is not suspended in the middle of a write. **Resume** starts the next waiting task.
- **Cancel selected** requests cancellation of selected waiting or active tasks. An active Sparse conversion stops at the converter's next safe cancellation point. QFIL assembly currently completes its current non-interruptible build step before the queue advances.
- **Skip selected** marks selected waiting tasks as skipped. Active Sparse tasks are cancelled safely and reported as skipped; active QFIL assembly completes its current build step before the queue advances.
- **Cancel queue** cancels the active task and prevents remaining tasks from starting.

Queue order and task membership are locked during execution; selection and status filtering remain available.

## Retry and reports

After the run, select failed, cancelled, or skipped items and choose **Retry selected**. Only the selected items are placed back into the waiting state and submitted to a new sequential run. Successful items are not repeated automatically.

The overall progress bar advances by task completion and current-task progress. This is task-weighted rather than a byte-weighted estimate, so files of different sizes contribute equally to the completed-task portion. The batch JSON report records each item type, status, errors, output paths, QFIL manifest/search inputs, and Sparse verification results where enabled. QFIL patch commands are reported by the QFIL backend but are not executed.

A failed task does not stop later tasks. Preflight failure is different: it blocks the entire selected run before any output is produced.

Batch profiles and mixed Sparse/QFIL queue support are included in the v0.6.0 release candidate. These features are not included in older release binaries.
