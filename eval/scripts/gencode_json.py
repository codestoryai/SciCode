import argparse
from pathlib import Path

from scicode.parse.parse import (
    extract_function_name,
    get_function_from_code,
    read_from_jsonl
)
from scicode.gen.models import extract_python_script, get_model_function


DEFAULT_PROMPT_TEMPLATE = Path("eval", "data", "background_comment_template.txt").read_text()


class Gencode:
    def __init__(self, model: str, output_dir: Path,
                 prompt_dir: Path, temperature: float):
        self.model = model
        self.output_dir = output_dir
        self.prompt_dir = prompt_dir
        self.temperature = temperature
        self.previous_llm_code = []

    def save_prompt_with_steps(self, prob_data: dict, prompt: str, num_steps: int, tot_steps: int) -> None:
        output_dir = Path(self.prompt_dir, self.model)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file_path = output_dir / f"{prob_data['problem_id']}.{num_steps}.txt"
        output_file_path.write_text(prompt, encoding="utf-8")

    def save_response_with_steps(self, prob_data: dict, response: str, previous_code: str,
                                 num_steps: int, model="gpt-4o",) -> None:
        output_dir = (
                self.output_dir / model
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        prob_id = prob_data["problem_id"]
        output_file_path = output_dir / f"{prob_id}.{num_steps}.py"
        python_code = extract_python_script(response)
        output_file_path.write_text(f'{previous_code}\n{python_code}', encoding="utf-8")

    def generate_response_with_steps(
        self, prob_data: dict, num_steps: int, tot_steps: int, model="gpt-4o",
            prompt_template=DEFAULT_PROMPT_TEMPLATE,
            *, save: bool = True) -> None:
        """

        Args:
            prob_data (dict): dict of the problem
            num_steps (int): Current generating step
            tot_steps (int): Total step of the problem
            model (str)
            prompt_template (str)
            save (bool, optional): Save propmt and model response. Defaults to True.
        """
        prob_id = prob_data["problem_id"]
        if num_steps == 1:
            self.previous_llm_code = [None] * tot_steps
        else:
            if len(self.previous_llm_code) != tot_steps:
                self.previous_llm_code = [None] * tot_steps
            for prev_step in range(num_steps - 1):
                if self.previous_llm_code[prev_step] is None:
                    if (prob_id == "13" and prev_step == 5) or (prob_id == "62" and prev_step == 0)\
                            or (prob_id == "76" and prev_step == 2):
                        prev_file_path = Path("eval", "data", f"{prob_id}.{prev_step+1}.txt")
                    else:
                        prev_file_path = (
                                self.output_dir
                                / model
                                / f"{prob_id}.{prev_step + 1}.py"
                        )
                    if prev_file_path.is_file():
                        prev_file_content = prev_file_path.read_text(encoding='utf-8')
                        func_name = extract_function_name(prob_data["sub_steps"][prev_step]["function_header"])
                        function_code = get_function_from_code(prev_file_content, func_name)
                        self.previous_llm_code[prev_step] = function_code
                    else:
                        raise Exception(f'Generating {prob_id} step {num_steps} ahead of step {prev_step + 1}.')
        prompt, previous_code = self.generate_prompt_with_steps(prob_data, num_steps, prompt_template)
        if save:
            self.save_prompt_with_steps(prob_data, prompt, num_steps, tot_steps)

        model_kwargs = {}
        if "claude" in model:
            model_kwargs["max_tokens"] = 4096
        model_kwargs["temperature"] = self.temperature
        # write the response to a file if it doesn't exist
        output_file_path = (
                self.output_dir
                / model
                / f"{prob_id}.{num_steps}.py"
        )
        if not output_file_path.exists():
            model_fct = get_model_function(model, **model_kwargs)
            response_from_llm = model_fct(prompt)
            self.previous_llm_code[num_steps - 1] = extract_python_script(response_from_llm)
            self.save_response_with_steps(prob_data, response_from_llm, previous_code, num_steps, model)

    @staticmethod
    def process_problem_code(prob_data: dict, num_steps: int) -> str:
        header_docstring = prob_data['sub_steps'][num_steps - 1]['function_header']
        return_str = prob_data['sub_steps'][num_steps - 1]['return_line']
        string = f"{header_docstring}\n\n{return_str}"
        return string

    def process_problem_steps(self, problem_data: dict, num_steps: int):
        """Process problem data and return previous steps and next steps"""
        output_lines = []
        next_step = []
        previous_code = []
        for i in range(num_steps - 1):
            output_lines.append(self.previous_llm_code[i])
            previous_code.append(self.previous_llm_code[i])
            output_lines.append("------")

        next_step.append(problem_data["sub_steps"][num_steps - 1]["step_description_prompt"])
        next_step.append(self.process_problem_code(problem_data, num_steps))
        output_str = "\n\n".join(output_lines[:-1])  # Remove the last "------"
        next_step_str = "\n\n".join(next_step)
        previous_code_str = "\n".join(previous_code)
        return output_str, next_step_str, previous_code_str

    def generate_prompt_with_steps(self, prob_data: dict, num_steps: int,
                                   prompt_template=DEFAULT_PROMPT_TEMPLATE):
        # parse the input file and extract the content

        problem_steps_str, next_step_str, previous_code_str = self.process_problem_steps(prob_data,
                                                                                         num_steps)
        dependencies = prob_data["required_dependencies"]
        assert next_step_str
        return prompt_template.format(
            problem_steps_str=problem_steps_str,
            next_step_str=next_step_str,
            dependencies=dependencies,
        ), f'{dependencies}\n{previous_code_str}\n'


def get_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
    )
    parser.add_argument(
        "--model", type=str, default="gpt-4o", help="Model name"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("eval_results", "generated_code"),
        help="Output directory",
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        default=Path("eval", "data", "problems_all.jsonl"),
        help="Input directory",
    )
    parser.add_argument(
        "--prompt-dir",
        type=Path,
        default=Path("eval_results", "prompt"),
        help="Prompt directory",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0,
        help="Generation temperature",
    )
    return parser


def main(model: str,
         output_dir: Path,
         input_path: Path,
         prompt_dir: Path,
         temperature: float
) -> None:
    gcode = Gencode(
        model=model, output_dir=output_dir,
        prompt_dir=prompt_dir,  temperature=temperature
    )
    data = read_from_jsonl(input_path)
    for problem in data:
        prob_id = problem['problem_id']
        steps = len(problem['sub_steps'])
        print(f'Generating {prob_id}...')
        for i in range(steps):
            if (prob_id == "13" and i == 5) or (prob_id == "62" and i == 0)\
                    or (prob_id == "76" and i == 2):
                continue
            gcode.generate_response_with_steps(problem, i + 1, steps, model)


if __name__ == "__main__":
    args = get_cli().parse_args()
    main(**vars(args))
