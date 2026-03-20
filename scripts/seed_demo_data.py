from app import create_app
from demo_data import format_demo_summary, seed_demo_data


def main():
    app = create_app()
    with app.app_context():
        summary = seed_demo_data()
        print("Demo veri üretimi tamamlandı.")
        print(format_demo_summary(summary))


if __name__ == "__main__":
    main()
