"""
readInput.py - A module for reading and processing user input
"""


def read_user_input(prompt: str = "Enter input: ") -> str:
    """
    Read a single line of input from the user.
    
    Args:
        prompt: The prompt to display to the user
        
    Returns:
        The user's input as a string
    """
    return input(prompt)


def read_multiple_inputs(count: int, prompt: str = "Enter input {}: ") -> list:
    """
    Read multiple lines of input from the user.
    
    Args:
        count: Number of inputs to read
        prompt: The prompt template to display (can include {})
        
    Returns:
        A list of user inputs
    """
    inputs = []
    for i in range(1, count + 1):
        user_input = input(prompt.format(i))
        inputs.append(user_input)
    return inputs


def read_integer(prompt: str = "Enter an integer: ") -> int:
    """
    Read an integer input from the user with error handling.
    
    Args:
        prompt: The prompt to display to the user
        
    Returns:
        The input converted to an integer
    """
    while True:
        try:
            return int(input(prompt))
        except ValueError:
            print("Invalid input. Please enter a valid integer.")


if __name__ == "__main__":
    # Example usage
    print("Welcome to readInput module!")
    name = read_user_input("What is your name? ")
    print(f"Hello, {name}!")
