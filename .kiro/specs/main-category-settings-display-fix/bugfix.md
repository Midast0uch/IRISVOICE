# Bugfix Requirements Document

## Introduction

After implementing the wheelview-navigation-integration spec, users are experiencing a bug where clicking any of the 6 main category nodes at Level 2 shows "no setting available for this category" instead of displaying the WheelView with settings. The WheelView component expects a populated `miniNodeStack` to render the dual-ring mechanism and side panel, but when transitioning from Level 2 to Level 3 via main category selection, the `miniNodeStack` remains empty because it is only populated during sub-node selection (SELECT_SUB action).

The root cause is that the navigation flow assumes users will select a sub-node to populate the mini-node stack, but the current implementation allows direct main category selection which bypasses sub-node selection, leaving the WheelView without data to display.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a user clicks any of the 6 main category nodes at Level 2 THEN the system transitions to Level 3 with `selectedMain` set but `miniNodeStack` remains empty

1.2 WHEN the WheelView component renders with an empty `miniNodeStack` THEN the system displays "No settings available for this category" message instead of the wheel view

1.3 WHEN the SELECT_MAIN action is dispatched THEN the system does not populate `miniNodeStack` with the main category's mini-nodes

### Expected Behavior (Correct)

2.1 WHEN a user clicks a main category node at Level 2 THEN the system SHALL populate `miniNodeStack` with all mini-nodes associated with that main category

2.2 WHEN the WheelView component renders with a populated `miniNodeStack` THEN the system SHALL display the dual-ring mechanism with sub-nodes and mini-nodes

2.3 WHEN the SELECT_MAIN action is dispatched THEN the system SHALL either auto-select the first sub-node or aggregate all mini-nodes from all sub-nodes under that main category

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a user navigates using the GO_BACK action from Level 3 THEN the system SHALL CONTINUE TO transition to Level 2 correctly

3.2 WHEN a user selects a sub-node explicitly (if that flow still exists) THEN the system SHALL CONTINUE TO populate `miniNodeStack` with that sub-node's mini-nodes

3.3 WHEN the WheelView component receives a populated `miniNodeStack` THEN the system SHALL CONTINUE TO render the dual-ring mechanism and side panel correctly

3.4 WHEN mini-node values are updated and confirmed THEN the system SHALL CONTINUE TO persist values to localStorage correctly
