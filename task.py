def save_task(self, name, details, existing_id=None):
        if existing_id is not None:
            for task in self.tasks:
                if task["id"] == existing_id:
                    task["title"] = name
                    task["description"] = details
                    return task

        item = {
            "id": str(uuid.uuid4()),
            "title": name,
            "description": details,
        }
        self.tasks.append(item)
        return item
