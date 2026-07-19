import { useMutation } from "@tanstack/react-query";

import type { ApiError } from "../../lib/api";
import { ask } from "../../lib/api";
import type { AskRequest, AskResponse } from "../../types/api";

/** Mutation, not query: a question is an action with a slow, rate-limited side
 *  effect (local-CPU generation), not cacheable server state. */
export function useAsk() {
  return useMutation<AskResponse, ApiError, AskRequest>({ mutationFn: ask });
}
