import uuid


def add(a , b):
    return a+b

result = add(2,5)

print(result)



def multiply(a, b):
    """
    Multiplies two numbers and returns the result.

    Args:
        a: The first number.
        b: The second number.

    Returns:
        The product of a and b.
    """
    return a * b


result2 = multiply(6, 7)
print(result2)


class TaskService:

    def __init__(self):
        self.tasks = []

    def create_task(self , title, description):

        task = {
            "id": str(uuid.uuid4()),
            "title":title,
            "description":description
        }

        self.tasks.append(task)
        return task
    
    def get_task(self, task_id):

        for task in self.tasks:
            if task["id"] == task_id:
                return task
            
        return None
    
    def get_all_tasks(self):
        return self.tasks
    
    def delete_tasks(self , task_id):

        for task in self.tasks:
            if task["id"] == task_id:
                self.tasks.remove(task)
                return task
        
        return None

