# simple-dbms

A simple database management system. 

Constructor University Bremen Database course homework assignment 

## Running the REPL

Use the following command:

```bash
python3 __main__.py
```

This will start the REPL using the default database path (`data/simple.db`).

To use a specific database file, pass the path as an argument:

```bash
python3 __main__.py <path-to-database>
```

Inside the REPL, you can execute SQL commands. Type `HELP;` for help, and `EXIT;` to quit.

## Running Tests

To run the project tests, use the following command:

```bash
python3 -m unittest discover tests
```
