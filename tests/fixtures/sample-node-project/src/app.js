import React from 'react';
import { render } from 'react-dom';
import express from 'express';
import chalk from 'chalk';

const app = express();
app.configure('development', () => {
  // Express 3.x style — removed in Express 4
});

const element = React.createElement('div', null, 'Hello');
render(element, document.getElementById('root'));

console.log(chalk.blue('Server starting...'));
app.listen(3000);
