from app import create_app

# Create the application
app = create_app()

if __name__ == '__main__':
    # Start the application in debug mode
    app.run(debug=True)
