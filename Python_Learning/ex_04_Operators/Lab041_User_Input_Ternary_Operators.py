user_age = int(input("Enter your age\n"))

if user_age >= 18:
    print("Yes You can go to GOA and vote")
else:
    print("Not you can't go and can't vote")

print("go to goa and vote" if user_age>=18 else "Can't go and vote")