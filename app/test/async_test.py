import asyncio


async def fuck():
    number1 = 114514
    number2 = 1919810
    print(f"{number1 + number2}第一次")
    return number1 + number2

result = fuck()
print("第二次")
print(result)


result2 = asyncio.run(result)
print(result2)





