from Agent import Agent

agent = Agent()
response, _ = agent.text_completion(text='特朗普哪一年出生的？', history=[])
print(response)