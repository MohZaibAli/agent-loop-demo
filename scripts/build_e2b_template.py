"""Build the custom E2B template: Python 3.12 + pytest + ripgrep. Run once.

    uv run python scripts/build_e2b_template.py
"""

import asyncio

from e2b import AsyncTemplate, Template

from agent.sandbox import E2B_TEMPLATE, WORKSPACE


def template() -> object:
    return (
        Template()
        .from_python_image("3.12")
        .apt_install(["ripgrep"], no_install_recommends=True)
        .pip_install(["pytest"])
        .make_dir(WORKSPACE)
        .set_workdir(WORKSPACE)
    )


async def main() -> None:
    info = await AsyncTemplate.build(template(), E2B_TEMPLATE, cpu_count=1, memory_mb=512,
                                     on_build_logs=lambda e: print(e.message))
    print(f"built template {E2B_TEMPLATE}: {info}")


if __name__ == "__main__":
    asyncio.run(main())
