"""Pure Qwen control using the same state and bounded-memory policy as Jev's helper."""
import json
from types import SimpleNamespace
from .jev_agent import JevAgent, DONE_OPTION, MAX_DONE_REFUSALS


class QwenSnapshotAgent(JevAgent):
    strict_qwen = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_llm_call_retries = 0

    def chat_completion(self, messages, tools=None):
        self._logical_turn += 1
        while True:
            state = self._state()
            pick, arguments = self._llm_decide(state, "direct_llm")
            if pick == DONE_OPTION:
                problems = self._done_problems(state["task"])
                if problems and self._llm_done_refusals < MAX_DONE_REFUSALS:
                    self._llm_done_refusals += 1
                    self._notes = [f'"done" was not accepted: {p}' for p in problems]
                    self.record_event("llm_done_refused", status="ok", reasons=problems)
                    continue
            break
        self._action_count += 1
        self._llm_decisions += 1
        self.record_event("llm_action" if self.name == "farm_llm_snapshot" else "qwen_action", status="ok", source="llm", action=pick, arguments=arguments)
        if pick == DONE_OPTION:
            return SimpleNamespace(role="assistant", content=DONE_OPTION, tool_calls=[])
        self._notes = []
        call = SimpleNamespace(id=f"qwen_call_{self._action_count}", type="function",
            function=SimpleNamespace(name=pick, arguments=json.dumps(arguments)))
        self.messages.messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": call.id, "type": "function", "function": {"name": pick, "arguments": call.function.arguments}}]})
        return SimpleNamespace(role="assistant", content=None, tool_calls=[call])

    def after_agent_run(self):
        super().after_agent_run()
        self.telemetry.update(decision_provider=None, decision_model=None,
            planning_mode="llm_snapshot" if self.name == "farm_llm_snapshot" else "qwen_snapshot", llm_calls=self._request_serial)
        self.record_event("qwen_controller_telemetry", status="ok", telemetry=dict(self.telemetry))
