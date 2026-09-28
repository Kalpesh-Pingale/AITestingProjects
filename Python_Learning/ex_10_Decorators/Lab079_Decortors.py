def add_security(func):
     def wrapper1():
        print("Before Action ->Add Helmet, Dashcash, gloves, knee guards, License")
        func()
        print("After Action -> Secure Driving, Leave all the items")
     return wrapper1()

@add_security
def drive_ola_scooter():
    print("I am driving ola scooter")

@add_security
def drive_zypp_scooter():
    print("Driving Zypp scooter") 