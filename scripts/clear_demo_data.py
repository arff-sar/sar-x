from app import create_app
from demo_data import clear_demo_data


def main():
    app = create_app()
    with app.app_context():
        result = clear_demo_data()
        print(f"Silinen demo kayıt sayısı: {result['deleted']}")


if __name__ == "__main__":
    main()
