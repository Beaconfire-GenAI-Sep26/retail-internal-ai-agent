// [13c] Proposal selectors — how components read state.proposals


// ═══════════════════════════════════════════════════════════════════
// 1. One proposal
// ═══════════════════════════════════════════════════════════════════
// Usage: useSelector((state) => selectProposal(state, id))
export const selectProposal = (state, proposalId) => state.proposals.byId[proposalId] ?? null;
export const selectProposalFetchStatus = (state, proposalId) => state.proposals.fetchStatusById[proposalId];
export const selectProposalFetchError = (state, proposalId) => state.proposals.fetchErrorById[proposalId] ?? null;


// ═══════════════════════════════════════════════════════════════════
// 2. Its edit / decision in progress or failed
// ═══════════════════════════════════════════════════════════════════
// → { kind: 'edit' | 'decide', status: 'loading' | 'failed', error } or null = nothing pending
export const selectProposalWrite = (state, proposalId) => state.proposals.writeById[proposalId] ?? null;
