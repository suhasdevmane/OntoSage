# Rasa Frontend (React)

Chat UI for the OntoBot stack. Connects to the Rasa server and renders rich responses, links, and media served by the file server.

## Available Scripts

In the project directory, you can run:

### `npm start`

Runs the app in development mode. Open http://localhost:3000

The page will reload when you make changes.\
You may also see any lint errors in the console.

### `npm test`

Launches the test runner in the interactive watch mode.\
See the section about [running tests](https://facebook.github.io/create-react-app/docs/running-tests) for more information.

### `npm run build`

Builds the app for production to the `build` folder.

The build is minified and the filenames include the hashes.\
Your app is ready to be deployed!

See the section about [deployment](https://facebook.github.io/create-react-app/docs/deployment) for more information.

### `npm run eject`

**Note: this is a one-way operation. Once you `eject`, you can't go back!**

If you aren't satisfied with the build tool and configuration choices, you can `eject` at any time. This command will remove the single build dependency from your project.

Instead, it will copy all the configuration files and the transitive dependencies (webpack, Babel, ESLint, etc) right into your project so you have full control over them. All of the commands except `eject` will still work, but they will point to the copied scripts so you can tweak them. At this point you're on your own.

You don't have to ever use `eject`. The curated feature set is suitable for small and middle deployments, and you shouldn't feel obligated to use this feature. However we understand that this tool wouldn't be useful if you couldn't customize it when you are ready for it.

## Configuration

- Rasa server URL is typically `http://localhost:5005` (via docker-compose). Adjust the client config if using a different host.
- Media links are served from the file server at `http://localhost:8080` (artifacts live under `/artifacts`).

## Customize for your building

- Modify prompts, labels, and inline help to match your site terminology.
- Add panels for common actions (e.g., “Show latest temperature in Room 101”).
- Keep intent names consistent with `rasa-ui` to ensure correct routing.

## End-to-end flow

1) User sends a message. 2) Rasa interprets and triggers an action. 3) The action fetches data and calls analytics if needed. 4) The frontend renders text + media from the file server.

### Code Splitting

This section has moved here: [https://facebook.github.io/create-react-app/docs/code-splitting](https://facebook.github.io/create-react-app/docs/code-splitting)

### Analyzing the Bundle Size

This section has moved here: [https://facebook.github.io/create-react-app/docs/analyzing-the-bundle-size](https://facebook.github.io/create-react-app/docs/analyzing-the-bundle-size)

### Making a Progressive Web App

This section has moved here: [https://facebook.github.io/create-react-app/docs/making-a-progressive-web-app](https://facebook.github.io/create-react-app/docs/making-a-progressive-web-app)

### Advanced Configuration

This section has moved here: [https://facebook.github.io/create-react-app/docs/advanced-configuration](https://facebook.github.io/create-react-app/docs/advanced-configuration)

### Deployment

This section has moved here: [https://facebook.github.io/create-react-app/docs/deployment](https://facebook.github.io/create-react-app/docs/deployment)

### `npm run build` fails to minify

See CRA troubleshooting: https://facebook.github.io/create-react-app/docs/troubleshooting#npm-run-build-fails-to-minify
