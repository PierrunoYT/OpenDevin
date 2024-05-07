from typing import List, Tuple, Dict

from opendevin.controller.agent import Agent
from opendevin.controller.state.state import State
from opendevin.events.action import (
    Action,
    AgentThinkAction,
    FileReadAction,
    FileWriteAction,
)
from opendevin.events.observation import Observation
from opendevin.llm.llm import LLM

from .parser import parse_command
from .prompts import (
    CONTEXT_PROMPT,
    MEMORY_FORMAT,
    NO_ACTION,
    STEP_PROMPT,
    SYSTEM_MESSAGE,
)


class SWEAgent(Agent):
    """
    An attempt to recreate swe_agent with output parsing, prompting style, and Application Computer Interface (ACI).

    SWE-agent includes ACI functions like 'goto', 'search_for', 'edit', 'scroll', 'run'
    """

    def __init__(self, llm: LLM) -> None:
        super().__init__(llm)
        self.memory_window: int = 4
        self.max_retries: int = 2
        self.running_memory: List[str] = []
        self.cur_file: str = ''
        self.cur_line: int = 0

    def _remember(self, action: Action, observation: Observation) -> None:
        """Agent has a limited memory of the few steps implemented as a queue"""
        memory: str = MEMORY_FORMAT(action.to_memory(), observation.to_memory())
        self.running_memory.append(memory)

    def _think_act(self, messages: List[Dict[str, str]]) -> Tuple[Action, str]:
        resp: Dict = self.llm.completion(
            messages=messages,
            temperature=0.05,
        )
        action_resp: str = resp['choices'][0]['message']['content']
        print(f"\033[1m\033[91m{resp['usage']}\033[0m")
        print(
            '\n==== RAW OUTPUT ====',
            f'\033[96m{action_resp}\033[0m',
            '==== END RAW ====\n',
            sep='\n',
        )
        return parse_command(action_resp, self.cur_file, self.cur_line)

    def _update(self, action: Action) -> None:
        if isinstance(action, (FileReadAction, FileWriteAction)):
            self.cur_file = action.path
            self.cur_line = action.start

    def step(self, state: State) -> Action:
        """
        SWE-Agent step:
            1. Get context - past actions, custom commands, current step
            2. Perform think-act - prompt model for action and reasoning
            3. Catch errors - ensure model takes action (5 attempts max)
        """
        for prev_action, obs in state.updated_info:
            self._remember(prev_action, obs)

        prompt: str = STEP_PROMPT(state.plan.main_goal, self.cur_file, self.cur_line)

        msgs: List[Dict[str, str]] = [
            {'content': SYSTEM_MESSAGE, 'role': 'system'},
            {'content': prompt, 'role': 'user'},
        ]

        if len(self.running_memory) > 0:
            context: str = CONTEXT_PROMPT(self.running_memory, self.memory_window)
            msgs.insert(1, {'content': context, 'role': 'user'})
        # clrs = [''] * (len(msgs)-2) + ['\033[0;36m', '\033[0;35m']
        # print('\n\n'.join([c+m['content']+'\033[0m' for c, m in zip(clrs, msgs)]))
        action, thought = self._think_act(messages=msgs)

        start_msg_len: int = len(msgs)
        while not action and len(msgs) < self.max_retries + start_msg_len:
            error: str = NO_ACTION(thought)
            error_msg: Dict[str, str] = {'content': error, 'role': 'user'}
            msgs.append(error_msg)
            action, thought = self._think_act(messages=msgs)

        if not action:
            action = AgentThinkAction(thought)

        self._update(action)
        self.latest_action = action
        return action

    def search_memory(self, query: str) -> List[str]:
        return [item for item in self.running_memory if query in item]

    def reset(self) -> None:
        """Used to reset the agent"""
        self.running_memory = []
        super().reset()