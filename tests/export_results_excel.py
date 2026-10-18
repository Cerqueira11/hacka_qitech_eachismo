import argparse
from pathlib import Path

from tests.utils.excel_report import create_workbook_from_log


DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "logs" / "dict_random_scenarios.log"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera uma planilha Excel a partir do log JSON do runner."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"Log JSON de entrada (padrão: {DEFAULT_LOG_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Arquivo Excel de saída (padrão: mesmo nome do log com extensão .xlsx)",
    )
    arguments = parser.parse_args()
    output_path = arguments.output or arguments.input.with_suffix(".xlsx")
    created_path = create_workbook_from_log(arguments.input, output_path)
    print(f"Planilha criada: {created_path.resolve()}")


if __name__ == "__main__":
    main()
