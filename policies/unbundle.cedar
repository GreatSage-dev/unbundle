// ==============================================================================
// UNBUNDLE: AWS Cedar Least-Privilege Authorization Policy
// Enforces mathematical boundary between cognitive reasoning & consequential action
// ==============================================================================

// Rule 1: Autonomous Observation & Analysis
// The agent has full autonomous permission to inspect, audit, and draft
permit(
    principal == Agent::"UNBUNDLE_Sentinel",
    action in [
        Action::"parse_document",
        Action::"audit_ncci_edits",
        Action::"check_carc_liability_shift",
        Action::"draft_statutory_appeal"
    ],
    resource == Resource::"MemberDispute"
);

// Rule 2: Consequential Dispatch Authorization
// Dispatching an appeal is ONLY permitted if explicit human cryptographic consent is present
permit(
    principal == Agent::"UNBUNDLE_Sentinel",
    action == Action::"dispatch_dispute",
    resource == Resource::"MemberDispute"
) when {
    context.human_approval_token_valid == true
};

// Rule 3: Explicit Forbid Safety Catch
// If token is missing, expired, or false, explicitly forbid with highest precedence
forbid(
    principal == Agent::"UNBUNDLE_Sentinel",
    action == Action::"dispatch_dispute",
    resource == Resource::"MemberDispute"
) unless {
    context.human_approval_token_valid == true
};
