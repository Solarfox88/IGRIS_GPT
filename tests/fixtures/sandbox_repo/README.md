# Calculator

A simple calculator module for testing IGRIS_GPT operational benchmarks.

## Usage

```python
from calculator import add, subtract, multiply, divide

result = add(2, 3)  # 5
```

## Known Issues

- `divide(a, 0)` raises `ZeroDivisionError` instead of `ValueError`
