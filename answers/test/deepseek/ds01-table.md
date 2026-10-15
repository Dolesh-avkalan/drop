# ds01 (deepseek)

- status: done
- chat: https://chat.deepseek.com/a/chat/s/1621d8d0-fa0e-461a-bf3b-89450b9321f9
- model: deepseek (deepthink off, search off)
- finished: 2026-10-15T11:51:56Z

## Question

Compare Python lists, tuples and sets in a markdown table (columns: type, mutable, ordered, duplicates allowed, typical use). Then give one short Python code block showing each.

## Answer

# Python Lists, Tuples, and Sets

| Type | Mutable | Ordered | Duplicates Allowed | Typical Use |
| --- | --- | --- | --- | --- |
| list | ✅ Yes | ✅ Yes | ✅ Yes | General-purpose sequences you need to modify (e.g., collections of items, queues) |
| tuple | ❌ No | ✅ Yes | ✅ Yes | Fixed collections / records that shouldn't change (e.g., coordinates, dict keys) |
| set | ✅ Yes | ❌ No | ❌ No | Fast membership tests & removing duplicates (e.g., unique values, set math) |

## Code Examples

```python
# List — mutable, ordered, allows duplicates
my_list = [1, 2, 2, 3]
my_list.append(4)
print(my_list)        # [1, 2, 2, 3, 4]

# Tuple — immutable, ordered, allows duplicates
my_tuple = (1, 2, 2, 3)
print(my_tuple[0])    # 1
# my_tuple[0] = 9     # ❌ TypeError: 'tuple' object does not support item assignment

# Set — mutable, unordered, no duplicates
my_set = {1, 2, 2, 3}
print(my_set)         # {1, 2, 3}  (duplicate 2 removed)
my_set.add(4)
print(my_set)         # {1, 2, 3, 4}
```

Quick rule of thumb:

- Need to change it? → list

- Need it fixed / hashable? → tuple

- Need uniqueness / fast in checks? → set
