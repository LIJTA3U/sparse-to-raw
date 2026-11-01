# Advanced task queue (v0.5.0 development)

The task queue processes Sparse images sequentially. It deliberately runs one conversion at a time to avoid competing disk-heavy operations.

## Preparing the queue

- Add one or more input images. Duplicate paths are ignored.
- Reorder waiting tasks by dragging rows or using **Move up / Move down**. The order shown is the processing order.
- Choose the output directory and overwrite policy.
- Choose whether to verify each written RAW file.
- Select a status filter to focus on waiting, running, successful, failed, cancelled, or skipped items.

## Controls while the queue is running

- **Pause** requests a pause at the next task boundary. The current file is allowed to finish; it is not suspended in the middle of a write. **Resume** starts the next waiting task.
- **Cancel selected** requests cancellation of selected waiting or active tasks. An active conversion stops at the converter's next safe cancellation point.
- **Skip selected** marks selected waiting tasks as skipped. If a selected task is active, it is cancelled safely and reported as skipped.
- **Cancel queue** cancels the active task and prevents remaining tasks from starting.

Queue order and task membership are locked during execution; selection and status filtering remain available.

## Retry and reports

After the run, select failed, cancelled, or skipped items and choose **Retry selected**. Only the selected items are placed back into the waiting state and submitted to a new sequential run. Successful items are not repeated automatically.

The overall progress bar advances by task completion and current-task progress. This is task-weighted rather than a byte-weighted estimate, so files of different sizes contribute equally to the completed-task portion. The batch JSON report records per-item status, errors, output paths, and verification results where enabled.

A failed task does not stop later tasks. Preflight failure is different: it blocks the entire selected run before any output is produced.

This feature is part of v0.5.0 development and is not included in the v0.4.0 release binaries.
