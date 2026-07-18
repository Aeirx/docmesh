"""Pure connection-scoring logic: no I/O, no repos, no async.

Each module computes one signal (semantic / entities / topics) plus the combiner;
GraphService orchestrates them. Everything here is unit-testable with hand-built
inputs. numpy at module top is fine in this package (it is a Phase 2 core dep and
cheap); spaCy/sklearn/scipy stay lazy inside functions per the model-import rule.
"""
