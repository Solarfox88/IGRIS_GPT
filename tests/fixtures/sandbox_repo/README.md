# Calculator

A simple calculator module for testing IGRIS_GPT operational benchmarks.

## Usage

```python
from calculator import add, subtract, multiply, divide

result = add(2, 3)  # 5
```

## Operation history

The sandbox calculator also records a simple in-memory history of operations.

```python
from calculator import clear_history, get_history, add

clear_history()
add(2, 3)
print(get_history())
```

## Known Issues

- `divide(a, 0)` now raises `ValueError` in the fixture
