def display_information(name, role):
    print(f"Name is : {name}, role is : {role}")
    print("name :", name, "& role :", role)



display_information(name="Pramod2", role="QA2")
display_information(role="QA3", name="Pramod3")

# Recommendation for your lab: use the f-string. 
# It's the modern standard (Python 3.6+), more readable, 
# and teaches you formatting you'll need everywhere. 
# The comma form is fine only for rough debugging.
