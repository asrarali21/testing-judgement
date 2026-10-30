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

    def save_task(self, name, details, existing_id=None):
        """
        Creates a new task or updates an existing one.

        If a task_id is provided and a matching task exists, its title and
        description are updated in-place. Otherwise, a brand-new task is
        created with a freshly generated UUID.

        Args:
            title (str):       The task title to set or update.
            description (str): The task description to set or update.
            task_id (str, optional): The ID of an existing task to update.
                                     Defaults to None (create mode).

        Returns:
            dict: The created or updated task dictionary.
        """
        if existing_id is not None:
            for task in self.tasks:
                if task["id"] == existing_id:
                    task["title"] = name
                    task["description"] = details
                    return task

        # No matching task found (or no id supplied) — create a new one
        item = {
            "id": str(uuid.uuid4()),
            "title": name,
            "description": details,
        }
        self.tasks.append(item)
        return item

