
class Messages:

    def __init__(self, provider="openai", system_message=None):
        """
        Initialize with the path to the GeoPackage.
        """
        self.provider = provider
        self.messages = [] # Conversation history
        self.runtime_metrics = [] # Storing tokens/runtime counts
        self.llm_responses = [] # Raw LLM engine responses (debug purposes)
        if system_message is not None:
            self.messages.append({"role": "system", "content": system_message}) 

    def user_input(self, input,time=None):
        self.messages.append({"role": "user", "content": input ,"time": time})

    def system_notify(self, input,time=None):
        self.messages.append({"role": "system", "content": input,"time": time})

    def llm_response(self, response, elapsed_time):

        # if tools is not None and response.choices[0].message.tool_calls:
        #     message_type = ToolCallRequestMessage
        #     response_tool_calls = []
        #     for tool in response.choices[0].message.tool_calls:
        #         tool_call = ToolCall(
        #             id=tool.id,
        #             name=tool.function.name,
        #             arguments=tool.function.arguments,
        #             tool_type=tool.type
        #         )
        #         response_tool_calls.append(tool_call)
        # else:
        #     message_type = ChatResponseMessage
        #     response_tool_calls = None

        self.messages.append(response.choices[0].message)
        usage = getattr(response, "usage", None)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        tokens = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "cached_tokens": getattr(prompt_details, "cached_tokens", 0) if prompt_details else 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
        }
        self.runtime_metrics.append({
            "role": "assistant",
            "time": elapsed_time,
            "tokens": tokens
        })
        

    def tool_call_response(self, tool_response, tool_call, elapsed_time,env_time):

        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": str(tool_response),
            "time": env_time
        })
        self.runtime_metrics.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "time": elapsed_time,
        })

    def context(self):
        return self.messages

    def __call__(self):
        return self.messages
    
