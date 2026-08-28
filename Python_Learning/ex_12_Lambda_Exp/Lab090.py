def triple_number(num):
    return num*3

result = triple_number(3)
print(result)


result_l_format = lambda num:num*3
print(result_l_format(3))


nums = [1, 2, 3, 4, 5]
evens = list(filter(lambda x: x % 2 == 0, nums))
print(evens)  # [2, 4]


items = [(2, 'b'), (1, 'a'), (3, 'c')]
items.sort(key=lambda x: x[0])
print(items)  # [(1, 'a'), (2, 'b'), (3, 'c')]
