class User:
    def __init__(self,Username: str,Values: dict,authType:str='local'):
        self.username=Username
        self.roles=Values['roles']
        self.password=Values['password']
        self.salt=Values['salt']
        self.authType=authType