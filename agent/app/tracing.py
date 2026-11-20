"""A-03 hooks for B-02 runners. This module never owns or persists graph state."""
import logging
import os
from contextlib import ExitStack, contextmanager
from time import perf_counter

from shared.observability import (bind_context, configure_logging, context_scope, correlation_id, log_context,
                                  log_event, redact, safe_id)
from shared.security import APIError


class Observation:
    def __init__(self, span=None):
        self.span = span

    def update(self, **values):
        if self.span is not None:
            try:
                self.span.update(**{key: redact(value) for key, value in values.items()})
            except Exception as exc:
                log_event("telemetry.update_failed", level=logging.WARNING, error_type=type(exc).__name__)


class Tracing:
    def __init__(self, client=None, *, callback_factory=None, propagate=None):
        self.client = client
        self._callback_factory = callback_factory
        self._propagate = propagate

    @classmethod
    def from_env(cls):
        public, secret = os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY")
        if os.getenv("LANGFUSE_TRACING_ENABLED", "true").lower() == "false" or not (public and secret):
            log_event("telemetry.disabled", service="agent")
            return cls()
        try:
            from langfuse import Langfuse, propagate_attributes
            from langfuse.langchain import CallbackHandler
            # The SDK installs an unfiltered HTTP logger during import.
            configure_logging("agent")

            class RedactedCallbackHandler(CallbackHandler):
                def _get_error_level_and_status_message(self, error):
                    # SDK error descriptions bypass its input/output mask. Preserve
                    # expected LangGraph interrupt semantics without exporting text.
                    level, _ = super()._get_error_level_and_status_message(error)
                    return level, type(error).__name__

            client = Langfuse(public_key=public, secret_key=secret,
                              base_url=os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")
                              or "https://cloud.langfuse.com",
                              environment=os.getenv("APP_ENV", "local"),
                              mask=lambda *, data, **_: redact(data))
            return cls(client, callback_factory=lambda: RedactedCallbackHandler(public_key=public),
                       propagate=propagate_attributes)
        except Exception as exc:
            log_event("telemetry.init_failed", level=logging.WARNING, error_type=type(exc).__name__)
            return cls()

    @property
    def enabled(self):
        return self.client is not None

    @contextmanager
    def observation(self, name, *, as_type="span", input=None, **attributes):
        """Export failures are best effort; business exceptions retain their type.

        Exit the SDK context *without* passing it a business exception: OpenTelemetry
        otherwise records the raw exception message/stack, bypassing Langfuse's mask.
        """
        started = perf_counter()
        manager = None
        observation = Observation()
        if self.client is not None:
            try:
                manager = self.client.start_as_current_observation(
                    name=name, as_type=as_type, input=redact(input),
                    **{key: redact(value) for key, value in attributes.items()})
                observation = Observation(manager.__enter__())
            except Exception as exc:
                manager = None
                log_event("telemetry.start_failed", level=logging.WARNING, error_type=type(exc).__name__)
        try:
            yield observation
        except BaseException as exc:
            error_type = type(exc).__name__
            details = {"error_type": error_type}
            if isinstance(exc, APIError):
                details.update(error_code=exc.code, status_code=exc.status)
            observation.update(level="ERROR", status_message=error_type,
                               metadata=details)
            log_event("agent.operation_failed", level=logging.ERROR, operation=name,
                      observation_type=as_type, **details,
                      duration_ms=round((perf_counter() - started) * 1000, 2))
            raise
        else:
            log_event("agent.operation", operation=name, observation_type=as_type,
                      duration_ms=round((perf_counter() - started) * 1000, 2))
        finally:
            if manager is not None:
                try:
                    manager.__exit__(None, None, None)
                except Exception as exc:
                    log_event("telemetry.end_failed", level=logging.WARNING, error_type=type(exc).__name__)

    @contextmanager
    def investigation(self, *, request_id, case_id, investigation_id, input=None):
        """One trace per start/resume segment; one session across all segments."""
        with context_scope(service="agent", request_id=correlation_id(request_id),
                           case_id=safe_id(case_id, "case_id"),
                           investigation_id=safe_id(investigation_id, "investigation_id"), trace_id=None):
            with ExitStack() as stack:
                if self._propagate:
                    try:
                        stack.enter_context(self._propagate(
                            trace_name="investigation", session_id=log_context()["investigation_id"],
                            metadata={key: str(value) for key, value in log_context().items() if value is not None}))
                    except Exception as exc:
                        log_event("telemetry.propagation_failed", level=logging.WARNING, error_type=type(exc).__name__)
                with self.observation("investigation", input=input, metadata=log_context()) as root:
                    if self.client:
                        try:
                            bind_context(trace_id=self.client.get_current_trace_id())
                        except Exception:
                            pass
                    log_event("investigation.started")
                    yield root

    async def ainvoke(self, graph, state, *, request_id, case_id, investigation_id, config=None, **kwargs):
        """B-02 wraps each background run/resume here, with only IDs in checkpoints.

        Config is copied so a callback is never reused between simultaneous runs.
        A resume uses the new HTTP request ID and the same investigation/session ID.
        """
        with self.investigation(request_id=request_id, case_id=case_id,
                                investigation_id=investigation_id, input=state) as root:
            config = dict(config or {})
            if self._callback_factory:
                try:
                    config["callbacks"] = [*config.get("callbacks", []), self._callback_factory()]
                except Exception as exc:
                    log_event("telemetry.callback_failed", level=logging.WARNING, error_type=type(exc).__name__)
            result = await graph.ainvoke(state, config=config, **kwargs)
            root.update(output=result)
            log_event("investigation.finished", status=result.get("status") if isinstance(result, dict) else None)
            return result

    async def model_call(self, client, *, prompt_template, **kwargs):
        """Trace a direct Anthropic call (LangChain callbacks cannot see this SDK).

        prompt_template is a source-controlled template/version, never user text.
        The actual message content is withheld by the privacy filter. Structured
        evidence can be traced on the enclosing reason/tool observation.
        """
        with self.observation("reason.model", as_type="generation", model=kwargs["model"],
                              input={"prompt_template": prompt_template, "request": kwargs}) as generation:
            response = await client.messages.create(**kwargs)
            usage = response.usage
            counters = {key: getattr(usage, name, None) for key, name in
                        (("input", "input_tokens"), ("output", "output_tokens"),
                         ("cache_read_input_tokens", "cache_read_input_tokens"),
                         ("cache_creation_input_tokens", "cache_creation_input_tokens"))}
            generation.update(model=response.model, output=response.model_dump(mode="json"),
                              usage_details={key: value for key, value in counters.items() if value is not None})
            return response

    def flush(self):
        if self.client:
            try:
                self.client.flush()
            except Exception as exc:
                log_event("telemetry.flush_failed", level=logging.WARNING, error_type=type(exc).__name__)

    def shutdown(self):
        self.flush()
        if self.client:
            try:
                self.client.shutdown()
            except Exception as exc:
                log_event("telemetry.shutdown_failed", level=logging.WARNING, error_type=type(exc).__name__)
